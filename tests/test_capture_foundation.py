from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from capture_models import capture_observation_errors
from capture_provider import CaptureProvider, CaptureRequest, FakeOcrProvider
from food_candidate_factory import food_candidate_from_observation
from food_master_repository import JsonFoodMasterRepository
from food_resolver import build_food_knowledge_snapshot
from nutrition_label_parser import parse_nutrition_label_text
from personal_food_master import confirm_capture_food
from scripts.validate_pr12 import FakeSupabaseClient
from smart_food_capture import (
    calculate_daily_nutrition,
    capture_editor_nutrition_basis,
    prepare_food_candidate_editor_result,
    search_food_candidates,
)
from supabase_food_master_repository import SupabaseFoodMasterRepository


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads(
    (ROOT / "tests" / "fixtures" / "pr16_1_nutrition_labels.json").read_text(encoding="utf-8")
)


class NutritionLabelParserTests(unittest.TestCase):
    def parse(self, name: str) -> dict:
        return parse_nutrition_label_text(FIXTURES[name])

    def test_normal_japanese_label(self) -> None:
        result = self.parse("normal")
        self.assertEqual(
            result["nutrition"],
            {
                "basis": "per_item",
                "calories_kcal": 120.0,
                "protein_g": 3.2,
                "fat_g": 1.5,
                "carbs_g": 20.1,
                "sugar_g": None,
                "fiber_g": None,
                "salt_g": None,
            },
        )
        self.assertEqual(result["warnings"], [])

    def test_missing_macros_remain_missing(self) -> None:
        result = self.parse("missing_macros")
        self.assertEqual(result["nutrition"]["calories_kcal"], 180.0)
        self.assertIsNone(result["nutrition"]["protein_g"])
        self.assertIsNone(result["nutrition"]["fat_g"])
        self.assertIsNone(result["nutrition"]["carbs_g"])

    def test_numeric_ocr_confusions_are_contextual(self) -> None:
        result = self.parse("ocr_confusions")
        self.assertEqual(result["nutrition"]["calories_kcal"], 100.0)
        self.assertEqual(result["nutrition"]["protein_g"], 10.5)
        self.assertEqual(result["nutrition"]["fat_g"], 0.5)
        self.assertIn("ocr_numeric_substitution", {warning["code"] for warning in result["warnings"]})

    def test_malformed_decimal_is_not_guessed(self) -> None:
        result = self.parse("malformed_decimal")
        self.assertIsNone(result["nutrition"]["calories_kcal"])
        self.assertIsNone(result["nutrition"]["protein_g"])
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertTrue({"malformed_number", "malformed_decimal"} <= codes)

    def test_basis_and_content_size_are_separate(self) -> None:
        per_100g = self.parse("per_100g")
        per_100ml = self.parse("per_100ml")
        per_package = self.parse("per_package")
        self.assertEqual(per_100g["nutrition"]["basis"], "per_100g")
        self.assertEqual(per_100ml["nutrition"]["basis"], "per_100ml")
        self.assertEqual(per_package["nutrition"]["basis"], "per_package")
        self.assertEqual(per_100g["field_evidence"]["size"][0]["value"], "180g")
        self.assertEqual(per_100ml["field_evidence"]["size"][0]["value"], "250ml")

    def test_kcal_has_priority_over_kj(self) -> None:
        result = self.parse("kcal_and_kj")
        self.assertEqual(result["nutrition"]["calories_kcal"], 100.0)
        self.assertIn("mixed_energy_units", {warning["code"] for warning in result["warnings"]})

    def test_kj_only_is_derived_with_warning(self) -> None:
        result = self.parse("kj_only")
        self.assertEqual(result["nutrition"]["calories_kcal"], 100.0)
        self.assertIn("kj_converted", {warning["code"] for warning in result["warnings"]})

    def test_sugar_is_not_carbohydrates(self) -> None:
        result = self.parse("sugar_only")
        self.assertIsNone(result["nutrition"]["carbs_g"])
        self.assertIn("sugar_candidate_g", result["field_evidence"])
        self.assertIn("sugar_not_carbs", {warning["code"] for warning in result["warnings"]})

    def test_multiple_blocks_are_ambiguous(self) -> None:
        result = self.parse("multiple_blocks")
        self.assertEqual(result["nutrition"]["basis"], "unknown")
        self.assertIsNone(result["nutrition"]["calories_kcal"])
        self.assertIn("multiple_nutrition_blocks", {warning["code"] for warning in result["warnings"]})

    def test_invalid_values_are_rejected(self) -> None:
        result = self.parse("invalid_values")
        self.assertIsNone(result["nutrition"]["calories_kcal"])
        self.assertIsNone(result["nutrition"]["protein_g"])
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertTrue({"invalid_value", "invalid_per_100_value"} <= codes)


class CapturePipelineTests(unittest.TestCase):
    def observation(self) -> dict:
        provider: CaptureProvider = FakeOcrProvider()
        return provider.capture(
            CaptureRequest(
                FIXTURES["per_package"],
                identifiers=(("ean13", "4901234567894"),),
                hints={"suggested_name": "PR16.1 TEST FOOD", "ocr_confidence": 0.88},
            )
        )

    def candidate(self) -> dict:
        return food_candidate_from_observation(self.observation(), meal_type="snacks")

    def corrected_item(self) -> dict:
        return prepare_food_candidate_editor_result(
            self.candidate(),
            {
                "name": "PR16.1 確認食品",
                "meal_type": "snacks",
                "quantity": 3,
                "unit": "本",
                "consumed_quantity": 2,
                "nutrition": {
                    "basis": "per_item",
                    "calories_kcal": 99,
                    "protein_g": 3.0,
                    "fat_g": 0.5,
                    "carbs_g": 13.0,
                    "sugar_g": None,
                    "fiber_g": None,
                    "salt_g": None,
                },
                "source_mode": "user_label",
                "notes": "OCR result corrected by user",
            },
        )

    def test_fake_ocr_to_candidate_contract(self) -> None:
        observation = self.observation()
        self.assertEqual(capture_observation_errors(observation), [])
        self.assertEqual(observation["identifiers"], [{"type": "ean13", "value": "4901234567894"}])
        candidate = food_candidate_from_observation(observation)
        self.assertFalse(candidate["confirmed"])
        self.assertTrue(candidate["needs_review"])
        self.assertEqual(candidate["source_type"], "unknown")
        self.assertEqual(candidate["capture_metadata"]["capture_channel"], "label_ocr")
        self.assertEqual(candidate["capture_metadata"]["extraction_confidence"], 0.88)

    def test_editor_correction_uses_existing_prepare_path(self) -> None:
        original = self.candidate()
        original_copy = deepcopy(original)
        prepared = self.corrected_item()
        self.assertEqual(original, original_copy)
        self.assertEqual(prepared["source_type"], "user_label")
        self.assertTrue(prepared["confirmed"])
        self.assertEqual(prepared["canonical_name"], "PR16.1 確認食品")
        self.assertEqual(calculate_daily_nutrition([prepared])["totals"]["calories_kcal"], 198.0)

    def test_unknown_ocr_basis_requires_editor_confirmation(self) -> None:
        observation = FakeOcrProvider().capture(
            CaptureRequest(
                "エネルギー 99kcal たんぱく質 3g 脂質 0.5g 炭水化物 13g",
                hints={"suggested_name": "Basis未確認食品"},
            )
        )
        candidate = food_candidate_from_observation(observation)
        self.assertEqual(candidate["nutrition"]["basis"], "unknown")
        self.assertEqual(
            capture_editor_nutrition_basis(candidate["nutrition"], "本", preserve_unknown=True),
            "unknown",
        )
        with self.assertRaisesRegex(ValueError, "explicit basis"):
            prepare_food_candidate_editor_result(
                candidate,
                {
                    "name": "Basis未確認食品",
                    "meal_type": "snacks",
                    "quantity": 1,
                    "unit": "本",
                    "consumed_quantity": 1,
                    "nutrition": candidate["nutrition"],
                    "source_mode": "user_label",
                    "notes": None,
                },
            )

    def assert_repository_round_trip(self, repository: object, user_id: str) -> None:
        prepared = self.corrected_item()
        self.assertEqual(repository.cache_revision(), 0)
        self.assertEqual(repository.list_foods(user_id), [])
        self.assertEqual(repository.cache_revision(), 0, "Observation and Editor must not write")

        stored = confirm_capture_food(repository, user_id, prepared, now="2026-08-24T00:00:00+00:00")
        self.assertEqual(stored["status"], "active")
        self.assertEqual(repository.cache_revision(), 1)
        knowledge = build_food_knowledge_snapshot(repository.list_foods(user_id))
        suggestions = search_food_candidates("PR16.1 確認食品", knowledge)
        self.assertTrue(suggestions)
        restored = suggestions[0]
        self.assertEqual(restored["source_type"], "personal_master")
        self.assertEqual(
            {field: restored["nutrition"][field] for field in ("calories_kcal", "protein_g", "fat_g", "carbs_g")},
            {"calories_kcal": 99.0, "protein_g": 3.0, "fat_g": 0.5, "carbs_g": 13.0},
        )

    def test_json_repository_confirmation_and_immediate_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assert_repository_round_trip(
                JsonFoodMasterRepository(
                    Path(temp_dir) / "personal_food_master.json",
                    Path(temp_dir) / "food_encounters.jsonl",
                ),
                "pr16-json",
            )

    def test_supabase_adapter_confirmation_and_immediate_search(self) -> None:
        self.assert_repository_round_trip(
            SupabaseFoodMasterRepository(FakeSupabaseClient()),
            "pr16-supabase",
        )

    def test_capture_and_parser_layers_have_no_repository_import(self) -> None:
        for filename in ("capture_models.py", "capture_provider.py", "nutrition_label_parser.py"):
            source = (ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn("food_master_repository", source)
            self.assertNotIn("personal_food_master", source)


if __name__ == "__main__":
    unittest.main()
