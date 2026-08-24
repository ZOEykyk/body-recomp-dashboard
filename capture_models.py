from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, TypedDict


CAPTURE_CONTRACT_VERSION = "1.0"
CAPTURE_CHANNELS = {
    "label_ocr",
    "barcode",
    "manual",
    "personal_master",
    "external_product_db",
}


class CaptureIdentifier(TypedDict):
    type: str
    value: str


class CaptureFieldEvidence(TypedDict):
    raw_text: str
    raw_value: str | None
    value: Any
    unit: str | None
    status: str
    confidence: float | None


class CaptureWarning(TypedDict):
    code: str
    message: str
    field: str | None


class CaptureObservation(TypedDict):
    observation_id: str
    contract_version: str
    capture_channel: str
    provider: str
    provider_version: str
    image_sha256: str | None
    raw_text: str
    suggested_name: str | None
    field_evidence: dict[str, list[CaptureFieldEvidence]]
    identifiers: list[CaptureIdentifier]
    warnings: list[CaptureWarning]
    extraction_confidence: float | None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _confidence(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(number, 0.0), 1.0)


def normalize_capture_identifiers(values: Any) -> list[CaptureIdentifier]:
    identifiers: list[CaptureIdentifier] = []
    seen: set[tuple[str, str]] = set()
    for candidate in values if isinstance(values, list) else []:
        if not isinstance(candidate, dict):
            continue
        identifier_type = _text(candidate.get("type")).lower()
        identifier_value = _text(candidate.get("value"))
        key = (identifier_type, identifier_value)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        identifiers.append({"type": identifier_type, "value": identifier_value})
    return identifiers


def normalize_field_evidence(values: Any) -> dict[str, list[CaptureFieldEvidence]]:
    normalized: dict[str, list[CaptureFieldEvidence]] = {}
    if not isinstance(values, dict):
        return normalized
    for field, candidates in values.items():
        entries = candidates if isinstance(candidates, list) else []
        normalized_entries: list[CaptureFieldEvidence] = []
        for candidate in entries:
            if not isinstance(candidate, dict):
                continue
            normalized_entries.append(
                {
                    "raw_text": _text(candidate.get("raw_text")),
                    "raw_value": (
                        _text(candidate.get("raw_value"))
                        if candidate.get("raw_value") is not None
                        else None
                    ),
                    "value": deepcopy(candidate.get("value")),
                    "unit": _text(candidate.get("unit")) or None,
                    "status": _text(candidate.get("status")) or "candidate",
                    "confidence": _confidence(candidate.get("confidence")),
                }
            )
        if normalized_entries:
            normalized[_text(field)] = normalized_entries
    return normalized


def normalize_capture_warnings(values: Any) -> list[CaptureWarning]:
    warnings: list[CaptureWarning] = []
    for candidate in values if isinstance(values, list) else []:
        if not isinstance(candidate, dict) or not _text(candidate.get("code")):
            continue
        warnings.append(
            {
                "code": _text(candidate.get("code")),
                "message": _text(candidate.get("message")),
                "field": _text(candidate.get("field")) or None,
            }
        )
    return warnings


def build_capture_observation(
    *,
    capture_channel: str,
    provider: str,
    provider_version: str,
    raw_text: str,
    field_evidence: dict[str, list[dict[str, Any]]] | None = None,
    identifiers: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    image_sha256: str | None = None,
    suggested_name: str | None = None,
    extraction_confidence: float | None = None,
) -> CaptureObservation:
    """Build an immutable-by-convention observation with a deterministic id."""
    channel = _text(capture_channel).lower()
    normalized_image_hash = _text(image_sha256).lower() or None
    payload = {
        "capture_channel": channel,
        "provider": _text(provider),
        "provider_version": _text(provider_version),
        "image_sha256": normalized_image_hash,
        "raw_text": str(raw_text or ""),
        "suggested_name": _text(suggested_name) or None,
        "field_evidence": normalize_field_evidence(field_evidence),
        "identifiers": normalize_capture_identifiers(identifiers),
        "warnings": normalize_capture_warnings(warnings),
        "extraction_confidence": _confidence(extraction_confidence),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return {
        "observation_id": f"capture_observation_{hashlib.sha256(encoded).hexdigest()[:20]}",
        "contract_version": CAPTURE_CONTRACT_VERSION,
        **payload,
    }


def capture_observation_errors(observation: Any) -> list[str]:
    if not isinstance(observation, dict):
        return ["observation must be an object"]
    errors: list[str] = []
    if observation.get("capture_channel") not in CAPTURE_CHANNELS:
        errors.append("invalid capture_channel")
    for field in ("provider", "provider_version", "observation_id"):
        if not _text(observation.get(field)):
            errors.append(f"missing {field}")
    image_hash = observation.get("image_sha256")
    if image_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", str(image_hash)):
        errors.append("invalid image_sha256")
    if not isinstance(observation.get("field_evidence"), dict):
        errors.append("field_evidence must be an object")
    if not isinstance(observation.get("identifiers"), list):
        errors.append("identifiers must be an array")
    if not isinstance(observation.get("warnings"), list):
        errors.append("warnings must be an array")
    return errors


__all__ = [
    "CAPTURE_CHANNELS",
    "CAPTURE_CONTRACT_VERSION",
    "CaptureFieldEvidence",
    "CaptureIdentifier",
    "CaptureObservation",
    "CaptureWarning",
    "build_capture_observation",
    "capture_observation_errors",
    "normalize_capture_identifiers",
]
