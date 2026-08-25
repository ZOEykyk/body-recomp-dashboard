from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import re
import statistics
from threading import RLock
import time
from typing import Any, Callable, Protocol

from capture_models import CaptureObservation, build_capture_observation
from capture_provider import CaptureProvider, CaptureRequest
from food_candidate_factory import food_candidate_from_observation
from image_preprocessing import IMAGE_PREPROCESSING_VERSION, preprocess_label_image
from nutrition_label_parser import parse_nutrition_label_text


LABEL_OCR_PROVIDER_VERSION = "1.1"
DEFAULT_OCR_LANGUAGE = "jpn+eng"
DEFAULT_OCR_TIMEOUT_SECONDS = 15
OCR_CORE_NUTRITION_FIELDS = ("calories_kcal", "protein_g", "fat_g", "carbs_g")


class LabelOcrError(RuntimeError):
    """A user-safe OCR runtime failure that never embeds extracted text."""


class OcrEngine(Protocol):
    engine_name: str

    def version(self) -> str:
        ...

    def recognize(self, image: Any, *, language: str, timeout_seconds: int) -> dict[str, Any]:
        ...


class TesseractOcrEngine:
    engine_name = "tesseract"

    @staticmethod
    def _pytesseract() -> Any:
        try:
            import pytesseract
        except ImportError as exc:
            _set_ocr_runtime_state("error")
            raise LabelOcrError("OCR runtime is unavailable.") from exc
        return pytesseract

    def version(self) -> str:
        pytesseract = self._pytesseract()
        try:
            version = str(pytesseract.get_tesseract_version()).splitlines()[0]
        except Exception as exc:
            _set_ocr_runtime_state("error")
            raise LabelOcrError("Tesseract is unavailable.") from exc
        _set_ocr_runtime_state("ready")
        return version

    def recognize(self, image: Any, *, language: str, timeout_seconds: int) -> dict[str, Any]:
        pytesseract = self._pytesseract()
        try:
            available = set(pytesseract.get_languages(config=""))
            required = set(language.split("+"))
            if not required <= available:
                raise LabelOcrError("Japanese and English OCR language data are required.")
            started = time.perf_counter()
            data = pytesseract.image_to_data(
                image,
                lang=language,
                config="--oem 3 --psm 6",
                output_type=pytesseract.Output.DICT,
                timeout=timeout_seconds,
            )
        except LabelOcrError:
            _set_ocr_runtime_state("error")
            raise
        except RuntimeError as exc:
            _set_ocr_runtime_state("error")
            raise LabelOcrError("OCR execution timed out or failed.") from exc
        except Exception as exc:
            _set_ocr_runtime_state("error")
            raise LabelOcrError("OCR execution failed.") from exc

        lines: OrderedDict[tuple[int, int, int], list[str]] = OrderedDict()
        confidences: list[float] = []
        for index, raw_token in enumerate(data.get("text") or []):
            token = str(raw_token or "").strip()
            if not token:
                continue
            key = (
                int((data.get("block_num") or [0])[index]),
                int((data.get("par_num") or [0])[index]),
                int((data.get("line_num") or [0])[index]),
            )
            lines.setdefault(key, []).append(token)
            try:
                confidence = float((data.get("conf") or [-1])[index])
            except (TypeError, ValueError, IndexError):
                confidence = -1
            if confidence >= 0:
                confidences.append(confidence)
        raw_text = "\n".join(" ".join(tokens) for tokens in lines.values())
        _set_ocr_runtime_state("ready")
        return {
            "raw_text": raw_text,
            "confidence": round(statistics.mean(confidences) / 100, 4) if confidences else None,
            "token_count": sum(len(tokens) for tokens in lines.values()),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }


class OcrRuntimeCache:
    """Small process-local cache. Values are never written to files or external storage."""

    def __init__(self, max_entries: int = 8) -> None:
        self._max_entries = max(1, int(max_entries))
        self._values: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = RLock()

    def get_or_compute(
        self,
        key: str,
        compute: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            if key in self._values:
                self._values.move_to_end(key)
                return deepcopy(self._values[key]), True
        value = compute()
        with self._lock:
            self._values[key] = deepcopy(value)
            self._values.move_to_end(key)
            while len(self._values) > self._max_entries:
                self._values.popitem(last=False)
        return deepcopy(value), False

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def metadata(self) -> dict[str, Any]:
        """Return cache counters only; cache keys and OCR payloads remain private."""
        with self._lock:
            entry_count = len(self._values)
            return {
                "status": "populated" if entry_count else "empty",
                "entry_count": entry_count,
                "max_entries": self._max_entries,
            }


OCR_RUNTIME_CACHE = OcrRuntimeCache()
_OCR_RUNTIME_STATE_LOCK = RLock()
_OCR_RUNTIME_STATE = {"initialized": False, "status": "not_initialized"}


def _set_ocr_runtime_state(status: str) -> None:
    with _OCR_RUNTIME_STATE_LOCK:
        _OCR_RUNTIME_STATE.update({"initialized": True, "status": status})


def ocr_runtime_state() -> dict[str, Any]:
    with _OCR_RUNTIME_STATE_LOCK:
        return deepcopy(_OCR_RUNTIME_STATE)


def image_sha256(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def ocr_cache_key(
    image_hash: str,
    engine_name: str,
    engine_version: str,
    preprocessing_version: str,
    language: str,
) -> str:
    value = "|".join((image_hash, engine_name, engine_version, preprocessing_version, language))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _known_nutrition_count(parsed: dict[str, Any]) -> int:
    nutrition = parsed.get("nutrition") if isinstance(parsed, dict) else None
    if not isinstance(nutrition, dict):
        return 0
    return sum(nutrition.get(field) is not None for field in OCR_CORE_NUTRITION_FIELDS)


def normalize_ocr_text_for_parser(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Normalize common OCR spacing/spelling while preserving raw text separately."""
    normalized = str(text or "")
    warnings: list[dict[str, Any]] = []
    japanese = r"\u3040-\u30ff\u3400-\u9fff"
    compacted = re.sub(rf"(?<=[{japanese}0-9])[ \t\u3000]+(?=[{japanese}0-9])", "", normalized)
    if compacted != normalized:
        normalized = compacted
        warnings.append(
            {
                "code": "ocr_spacing_normalized",
                "message": "OCR character spacing was normalized and requires confirmation.",
                "field": None,
            }
        )
    corrected = normalized.replace("たんばく質", "たんぱく質").replace("タンバク質", "タンパク質")
    if corrected != normalized:
        normalized = corrected
        warnings.append(
            {
                "code": "ocr_protein_label_normalized",
                "message": "A common OCR protein-label spelling was normalized and requires confirmation.",
                "field": "protein_g",
            }
        )
    return normalized, warnings


class LabelOcrProvider(CaptureProvider):
    capture_channel = "label_ocr"
    provider_name = "tesseract_label_ocr"
    provider_version = LABEL_OCR_PROVIDER_VERSION

    def __init__(
        self,
        engine: OcrEngine | None = None,
        *,
        cache: OcrRuntimeCache | None = None,
        language: str = DEFAULT_OCR_LANGUAGE,
        timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
    ) -> None:
        self._engine = engine or TesseractOcrEngine()
        self._cache = cache or OCR_RUNTIME_CACHE
        self._language = language
        self._timeout_seconds = timeout_seconds
        self.last_metrics: dict[str, Any] = {}

    def cache_identity(self, image_hash: str) -> dict[str, str]:
        engine_version = self._engine.version()
        return {
            "image_sha256": image_hash,
            "engine": self._engine.engine_name,
            "engine_version": engine_version,
            "preprocessing_version": IMAGE_PREPROCESSING_VERSION,
            "language": self._language,
            "cache_key": ocr_cache_key(
                image_hash,
                self._engine.engine_name,
                engine_version,
                IMAGE_PREPROCESSING_VERSION,
                self._language,
            ),
        }

    def _extract(self, image_bytes: bytes) -> dict[str, Any]:
        preprocessed = preprocess_label_image(image_bytes)
        variant_specs = (
            (
                "enhanced_grayscale",
                preprocessed.primary,
                preprocessed.width,
                preprocessed.height,
            ),
            (
                "source_rgb",
                preprocessed.fallback,
                preprocessed.fallback_width,
                preprocessed.fallback_height,
            ),
        )
        results: list[dict[str, Any]] = []
        failures: list[LabelOcrError] = []
        for variant_name, image, width, height in variant_specs:
            try:
                recognized = self._engine.recognize(
                    image,
                    language=self._language,
                    timeout_seconds=self._timeout_seconds,
                )
            except LabelOcrError as exc:
                failures.append(exc)
                continue
            parser_text, _ = normalize_ocr_text_for_parser(recognized.get("raw_text") or "")
            parsed = parse_nutrition_label_text(parser_text)
            results.append(
                {
                    **recognized,
                    "variant": variant_name,
                    "width": width,
                    "height": height,
                    "field_count": _known_nutrition_count(parsed),
                }
            )
        if not results:
            raise failures[0] if failures else LabelOcrError("OCR execution failed.")

        selected = max(
            results,
            key=lambda result: (
                int(result.get("field_count") or 0),
                float(result.get("confidence") or 0),
                int(result.get("token_count") or 0),
            ),
        )
        variant_metrics = [
            {
                "variant": result["variant"],
                "width": result["width"],
                "height": result["height"],
                "field_count": result["field_count"],
                "confidence": result.get("confidence"),
                "ocr_ms": result.get("elapsed_ms"),
            }
            for result in results
        ]
        return {
            **selected,
            "elapsed_ms": round(sum(float(result.get("elapsed_ms") or 0) for result in results), 3),
            "selected_ocr_ms": selected.get("elapsed_ms"),
            "preprocessing_ms": preprocessed.elapsed_ms,
            "input_width": preprocessed.source_width,
            "input_height": preprocessed.source_height,
            "input_file_size_bytes": preprocessed.file_size_bytes,
            "input_format": preprocessed.source_format,
            "input_exif_present": preprocessed.exif_present,
            "input_exif_orientation": preprocessed.exif_orientation,
            "preprocessed_width": preprocessed.width,
            "preprocessed_height": preprocessed.height,
            "source_variant_width": preprocessed.fallback_width,
            "source_variant_height": preprocessed.fallback_height,
            "preprocessing_scale_factor": preprocessed.scale_factor,
            "preprocessing_resized": preprocessed.resized,
            "variant_metrics": variant_metrics,
            "variant_failure_count": len(failures),
        }

    def capture(self, request: CaptureRequest) -> CaptureObservation:
        if not isinstance(request.payload, bytes):
            raise LabelOcrError("Label OCR requires image bytes.")
        image_hash = image_sha256(request.payload)
        if request.image_sha256 and request.image_sha256 != image_hash:
            raise LabelOcrError("The uploaded image fingerprint is inconsistent.")
        identity = self.cache_identity(image_hash)
        lookup_started = time.perf_counter()
        extracted, cache_hit = self._cache.get_or_compute(
            identity["cache_key"],
            lambda: self._extract(request.payload),
        )
        cache_lookup_ms = round((time.perf_counter() - lookup_started) * 1000, 3)
        parser_text, adapter_warnings = normalize_ocr_text_for_parser(extracted.get("raw_text") or "")
        parsed = parse_nutrition_label_text(parser_text)
        evidence = deepcopy(parsed["field_evidence"])
        for candidates in evidence.values():
            for candidate in candidates:
                candidate["confidence"] = extracted.get("confidence")
        warnings = [*adapter_warnings, *deepcopy(parsed["warnings"])]
        if _known_nutrition_count(parsed) == 0:
            warnings.append(
                {
                    "code": "nutrition_not_detected",
                    "message": "Nutrition values were not detected; continue with manual input.",
                    "field": None,
                }
            )
        observation = build_capture_observation(
            capture_channel=self.capture_channel,
            provider=self.provider_name,
            provider_version=self.provider_version,
            image_sha256=image_hash,
            raw_text=extracted.get("raw_text") or "",
            suggested_name=request.hints.get("suggested_name"),
            field_evidence=evidence,
            identifiers=[{"type": kind, "value": value} for kind, value in request.identifiers],
            warnings=warnings,
            extraction_confidence=extracted.get("confidence"),
        )
        self.last_metrics = {
            "cache_hit": cache_hit,
            "cache_lookup_ms": cache_lookup_ms,
            "preprocessing_ms": extracted.get("preprocessing_ms"),
            "ocr_ms": extracted.get("elapsed_ms"),
            "candidate_fields": _known_nutrition_count(parsed),
            "token_count": extracted.get("token_count"),
            "variant": extracted.get("variant"),
            "input_width": extracted.get("input_width"),
            "input_height": extracted.get("input_height"),
            "input_file_size_bytes": extracted.get("input_file_size_bytes"),
            "input_format": extracted.get("input_format"),
            "input_exif_present": extracted.get("input_exif_present"),
            "input_exif_orientation": extracted.get("input_exif_orientation"),
            "preprocessed_width": extracted.get("preprocessed_width"),
            "preprocessed_height": extracted.get("preprocessed_height"),
            "source_variant_width": extracted.get("source_variant_width"),
            "source_variant_height": extracted.get("source_variant_height"),
            "preprocessing_scale_factor": extracted.get("preprocessing_scale_factor"),
            "preprocessing_resized": extracted.get("preprocessing_resized"),
            "variant_metrics": deepcopy(extracted.get("variant_metrics") or []),
            "variant_failure_count": extracted.get("variant_failure_count"),
            "selected_ocr_ms": extracted.get("selected_ocr_ms"),
            "engine": identity["engine"],
            "engine_version": identity["engine_version"],
            "preprocessing_version": identity["preprocessing_version"],
        }
        return observation


def capture_label_image(
    image_bytes: bytes,
    *,
    suggested_name: str | None = None,
    provider: LabelOcrProvider | None = None,
) -> dict[str, Any]:
    runtime = provider or LabelOcrProvider()
    started = time.perf_counter()
    observation = runtime.capture(
        CaptureRequest(
            payload=image_bytes,
            image_sha256=image_sha256(image_bytes),
            hints={"suggested_name": suggested_name},
        )
    )
    candidate_started = time.perf_counter()
    candidate = food_candidate_from_observation(observation)
    candidate_ms = (time.perf_counter() - candidate_started) * 1000
    return {
        "observation": observation,
        "candidate": candidate,
        "metrics": {
            **deepcopy(runtime.last_metrics),
            "candidate_ms": round(candidate_ms, 3),
            "total_ms": round((time.perf_counter() - started) * 1000, 3),
        },
    }


__all__ = [
    "DEFAULT_OCR_LANGUAGE",
    "LABEL_OCR_PROVIDER_VERSION",
    "LabelOcrError",
    "LabelOcrProvider",
    "OCR_RUNTIME_CACHE",
    "OcrRuntimeCache",
    "TesseractOcrEngine",
    "capture_label_image",
    "image_sha256",
    "ocr_cache_key",
    "ocr_runtime_state",
    "normalize_ocr_text_for_parser",
]
