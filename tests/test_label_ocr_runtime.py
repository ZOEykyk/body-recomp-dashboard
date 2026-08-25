from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from capture_provider import CaptureRequest
from food_candidate_factory import food_candidate_from_observation
from food_master_repository import JsonFoodMasterRepository
from food_resolver import build_food_knowledge_snapshot
from image_preprocessing import (
    IMAGE_PREPROCESSING_VERSION,
    ImagePreprocessingError,
    inspect_label_image_metadata,
    preprocess_label_image,
)
from label_ocr_runtime import (
    LabelOcrError,
    LabelOcrProvider,
    OcrRuntimeCache,
    capture_label_image,
    image_sha256,
    normalize_ocr_text_for_parser,
)
from personal_food_master import confirm_capture_food
from scripts.validate_pr12 import FakeSupabaseClient
from smart_food_capture import (
    calculate_daily_nutrition,
    canonical_builder_result,
    prepare_food_candidate_editor_result,
    search_food_candidates,
)
from supabase_food_master_repository import SupabaseFoodMasterRepository


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (ROOT / "tests" / "fixtures" / "pr16_2_label_cases.json").read_text(encoding="utf-8")
)


def image_fixture(*, low_contrast: bool = False, rotated: bool = False) -> bytes:
    background = 180 if low_contrast else 255
    foreground = 150 if low_contrast else 0
    image = Image.new("RGB", (520, 260), (background, background, background))
    for y in range(30, 220, 35):
        for x in range(30, 480):
            if (x + y) % 11 < 5:
                image.putpixel((x, y), (foreground, foreground, foreground))
    if rotated:
        image = image.rotate(5, expand=True, fillcolor=(255, 255, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeImageOcrEngine:
    engine_name = "fake_tesseract"

    def __init__(self, text: str, *, confidence: float = 0.88, fail: bool = False) -> None:
        self.text = text
        self.confidence = confidence
        self.fail = fail
        self.calls = 0

    def version(self) -> str:
        return "5.fake"

    def recognize(self, image: object, *, language: str, timeout_seconds: int) -> dict:
        del image, language, timeout_seconds
        self.calls += 1
        if self.fail:
            raise LabelOcrError("OCR execution failed.")
        return {
            "raw_text": self.text,
            "confidence": self.confidence,
            "token_count": len(self.text.split()),
            "elapsed_ms": 12.0,
        }


class SequencedImageOcrEngine:
    engine_name = "fake_tesseract"

    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.calls = 0

    def version(self) -> str:
        return "5.fake"

    def recognize(self, image: object, *, language: str, timeout_seconds: int) -> dict:
        del image, language, timeout_seconds
        result = self.results[self.calls]
        self.calls += 1
        return {
            "raw_text": result["text"],
            "confidence": result["confidence"],
            "token_count": len(result["text"].split()),
            "elapsed_ms": result.get("elapsed_ms", 12.0),
        }


class ImagePreprocessingTests(unittest.TestCase):
    def test_preprocessing_normalizes_and_times_image(self) -> None:
        result = preprocess_label_image(image_fixture(low_contrast=True, rotated=True))
        self.assertEqual(result.primary.mode, "L")
        self.assertEqual(result.fallback.mode, "RGB")
        self.assertGreater(result.width, 0)
        self.assertGreater(result.height, 0)
        self.assertEqual(result.source_format, "PNG")
        self.assertEqual(IMAGE_PREPROCESSING_VERSION, "1.1")
        self.assertGreaterEqual(result.elapsed_ms, 0)

    def test_low_resolution_input_is_upscaled_without_resizing_source_variant(self) -> None:
        image = Image.new("RGB", (900, 600), "white")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=95)
        result = preprocess_label_image(buffer.getvalue())
        self.assertEqual((result.source_width, result.source_height), (900, 600))
        self.assertEqual((result.fallback_width, result.fallback_height), (900, 600))
        self.assertEqual((result.width, result.height), (2200, 1467))
        self.assertAlmostEqual(result.scale_factor, 2200 / 900, places=3)

    def test_typical_iphone_resolution_is_not_downscaled(self) -> None:
        image = Image.new("RGB", (4032, 3024), "white")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        result = preprocess_label_image(buffer.getvalue())
        self.assertEqual((result.source_width, result.source_height), (4032, 3024))
        self.assertEqual((result.width, result.height), (4032, 3024))
        self.assertEqual((result.fallback_width, result.fallback_height), (4032, 3024))
        self.assertEqual(result.scale_factor, 1.0)
        self.assertFalse(result.resized)

    def test_metadata_exposes_only_safe_exif_summary(self) -> None:
        image = Image.new("RGB", (120, 60), "white")
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = "private description"
        buffer = BytesIO()
        image.save(buffer, format="JPEG", exif=exif)
        metadata = inspect_label_image_metadata(buffer.getvalue())
        self.assertEqual(metadata["exif_orientation"], 6)
        self.assertTrue(metadata["exif_present"])
        self.assertNotIn("private description", json.dumps(metadata))

    def test_exif_orientation_is_applied(self) -> None:
        image = Image.new("RGB", (120, 60), "white")
        exif = Image.Exif()
        exif[274] = 6
        buffer = BytesIO()
        image.save(buffer, format="JPEG", exif=exif)
        result = preprocess_label_image(buffer.getvalue())
        self.assertGreater(result.height, result.width)

    def test_corrupt_image_is_rejected_without_payload_leak(self) -> None:
        with self.assertRaisesRegex(ImagePreprocessingError, "could not be decoded"):
            preprocess_label_image(b"not-an-image-private-content")


class LabelOcrProviderTests(unittest.TestCase):
    def test_ocr_character_spacing_is_normalized_for_parser_only(self) -> None:
        raw = "1 個 あ た り\nた ん ば く 質 3.2 g"
        normalized, warnings = normalize_ocr_text_for_parser(raw)
        self.assertEqual(normalized, "1個あたり\nたんぱく質3.2 g")
        self.assertEqual(
            {item["code"] for item in warnings},
            {"ocr_spacing_normalized", "ocr_protein_label_normalized"},
        )

    def test_japanese_label_fixture_contracts(self) -> None:
        for name, fixture in CASES.items():
            with self.subTest(name=name):
                engine = FakeImageOcrEngine(fixture["text"])
                provider = LabelOcrProvider(engine, cache=OcrRuntimeCache())
                result = capture_label_image(
                    image_fixture(
                        low_contrast=name == "low_contrast",
                        rotated=name == "slightly_rotated",
                    ),
                    suggested_name=f"PR16.2 {name}",
                    provider=provider,
                )
                candidate = result["candidate"]
                self.assertEqual(candidate["nutrition"]["basis"], fixture["basis"])
                known = sum(
                    candidate["nutrition"].get(field) is not None
                    for field in ("calories_kcal", "protein_g", "fat_g", "carbs_g")
                )
                self.assertEqual(known, fixture["known_fields"])
                self.assertFalse(candidate["confirmed"])
                self.assertTrue(candidate["needs_review"])
                self.assertEqual(candidate["source_type"], "unknown")
                self.assertEqual(candidate["capture_metadata"]["capture_channel"], "label_ocr")
                self.assertEqual(provider.last_metrics["candidate_fields"], fixture["known_fields"])

    def test_same_runtime_identity_uses_process_cache(self) -> None:
        engine = FakeImageOcrEngine(CASES["standard_vertical"]["text"])
        cache = OcrRuntimeCache()
        image = image_fixture()
        first = LabelOcrProvider(engine, cache=cache)
        first.capture(CaptureRequest(image, image_sha256=image_sha256(image)))
        second = LabelOcrProvider(engine, cache=cache)
        second.capture(CaptureRequest(image, image_sha256=image_sha256(image)))
        self.assertEqual(engine.calls, 2)
        self.assertFalse(first.last_metrics["cache_hit"])
        self.assertTrue(second.last_metrics["cache_hit"])

    def test_camera_and_upload_bytes_share_image_cache_identity(self) -> None:
        engine = FakeImageOcrEngine(CASES["standard_vertical"]["text"])
        cache = OcrRuntimeCache()
        camera_bytes = image_fixture()
        uploaded_bytes = bytes(camera_bytes)
        provider = LabelOcrProvider(engine, cache=cache)

        provider.capture(CaptureRequest(camera_bytes, image_sha256=image_sha256(camera_bytes)))
        provider.capture(CaptureRequest(uploaded_bytes, image_sha256=image_sha256(uploaded_bytes)))

        self.assertEqual(image_sha256(camera_bytes), image_sha256(uploaded_bytes))
        self.assertEqual(engine.calls, 2)
        self.assertTrue(provider.last_metrics["cache_hit"])

    def test_source_and_enhanced_variants_choose_higher_confidence_when_equally_complete(self) -> None:
        text = CASES["standard_vertical"]["text"]
        engine = SequencedImageOcrEngine(
            [
                {"text": text, "confidence": 0.70},
                {"text": text, "confidence": 0.94},
            ]
        )
        provider = LabelOcrProvider(engine, cache=OcrRuntimeCache())
        provider.capture(CaptureRequest(image_fixture()))
        self.assertEqual(provider.last_metrics["variant"], "source_rgb")
        self.assertEqual(provider.last_metrics["candidate_fields"], 4)
        self.assertEqual(len(provider.last_metrics["variant_metrics"]), 2)

    def test_more_complete_variant_wins_over_higher_confidence_partial_result(self) -> None:
        engine = SequencedImageOcrEngine(
            [
                {"text": CASES["partial_fields"]["text"], "confidence": 0.98},
                {"text": CASES["standard_vertical"]["text"], "confidence": 0.72},
            ]
        )
        provider = LabelOcrProvider(engine, cache=OcrRuntimeCache())
        provider.capture(CaptureRequest(image_fixture()))
        self.assertEqual(provider.last_metrics["variant"], "source_rgb")
        self.assertEqual(provider.last_metrics["candidate_fields"], 4)

    def test_metrics_compare_input_preprocessing_and_ocr_without_payload(self) -> None:
        provider = LabelOcrProvider(
            FakeImageOcrEngine(CASES["standard_vertical"]["text"]),
            cache=OcrRuntimeCache(),
        )
        result = capture_label_image(image_fixture(), provider=provider)
        metrics = result["metrics"]
        self.assertEqual((metrics["input_width"], metrics["input_height"]), (520, 260))
        self.assertGreater(metrics["preprocessed_width"], metrics["input_width"])
        self.assertEqual((metrics["source_variant_width"], metrics["source_variant_height"]), (520, 260))
        serialized = json.dumps(metrics, ensure_ascii=False)
        self.assertNotIn("栄養成分表示", serialized)
        self.assertNotIn("image_sha256", serialized)

    def test_unreadable_image_returns_reviewable_manual_candidate(self) -> None:
        engine = FakeImageOcrEngine("")
        provider = LabelOcrProvider(engine, cache=OcrRuntimeCache())
        observation = provider.capture(CaptureRequest(image_fixture()))
        candidate = food_candidate_from_observation(observation)
        self.assertEqual(provider.last_metrics["candidate_fields"], 0)
        self.assertIn("nutrition_not_detected", {item["code"] for item in observation["warnings"]})
        self.assertFalse(candidate["confirmed"])
        self.assertTrue(candidate["needs_review"])

    def test_engine_failure_is_sanitized(self) -> None:
        provider = LabelOcrProvider(FakeImageOcrEngine("private", fail=True), cache=OcrRuntimeCache())
        with self.assertRaisesRegex(LabelOcrError, "OCR execution failed") as raised:
            provider.capture(CaptureRequest(image_fixture()))
        self.assertNotIn("private", str(raised.exception))


class LabelOcrIntegrationTests(unittest.TestCase):
    def confirmed_item(self) -> dict:
        provider = LabelOcrProvider(
            FakeImageOcrEngine(CASES["standard_vertical"]["text"]),
            cache=OcrRuntimeCache(),
        )
        candidate = capture_label_image(
            image_fixture(),
            suggested_name="PR16.2 確認食品",
            provider=provider,
        )["candidate"]
        return prepare_food_candidate_editor_result(
            candidate,
            {
                "name": "PR16.2 確認食品",
                "meal_type": "snacks",
                "quantity": 2,
                "unit": "個",
                "consumed_quantity": 1,
                "nutrition": candidate["nutrition"],
                "source_mode": "user_label",
                "notes": "user corrected",
            },
        )

    def assert_repository_flow(self, repository: object, user_id: str) -> None:
        item = self.confirmed_item()
        self.assertEqual(repository.cache_revision(), 0)
        self.assertEqual(repository.list_foods(user_id), [])
        self.assertEqual(calculate_daily_nutrition([item])["totals"]["calories_kcal"], 120.0)
        stored = confirm_capture_food(repository, user_id, item, now="2026-08-24T00:00:00+00:00")
        self.assertEqual(repository.cache_revision(), 1)
        knowledge = build_food_knowledge_snapshot(repository.list_foods(user_id))
        restored = search_food_candidates("PR16.2 確認食品", knowledge)[0]
        self.assertEqual(restored["source_type"], "personal_master")
        self.assertEqual(
            [restored["nutrition"][field] for field in ("calories_kcal", "protein_g", "fat_g", "carbs_g")],
            [120.0, 3.2, 1.5, 20.1],
        )
        serialized = json.dumps(stored, ensure_ascii=False)
        self.assertNotIn("栄養成分表示", serialized)
        self.assertNotIn("capture_metadata", serialized)

    def test_json_repository_confirmation_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assert_repository_flow(
                JsonFoodMasterRepository(
                    Path(temp_dir) / "personal_food_master.json",
                    Path(temp_dir) / "food_encounters.jsonl",
                ),
                "pr16-2-json",
            )

    def test_supabase_adapter_confirmation_and_restore(self) -> None:
        self.assert_repository_flow(SupabaseFoodMasterRepository(FakeSupabaseClient()), "pr16-2-supabase")

    def test_canonical_record_excludes_image_and_ocr_payload(self) -> None:
        item = self.confirmed_item()
        result = canonical_builder_result({"date": "2026-08-24"}, [item])
        serialized = json.dumps(result["canonical"], ensure_ascii=False)
        self.assertNotIn("栄養成分表示", serialized)
        self.assertNotIn("capture_metadata", serialized)
        self.assertNotIn("image_sha256", serialized)

    def test_runtime_modules_do_not_import_or_log_persistence_payloads(self) -> None:
        for filename in ("image_preprocessing.py", "label_ocr_runtime.py"):
            source = (ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn("food_master_repository", source)
            self.assertNotIn("supabase", source.lower())
            self.assertNotIn("print(", source)
            self.assertNotIn("logging", source)


if __name__ == "__main__":
    unittest.main()
