from __future__ import annotations

from copy import deepcopy
from typing import Any

from capture_models import CaptureObservation, capture_observation_errors
from food_lookup import NUTRITION_FIELDS
from smart_food_capture import unknown_candidate


FOOD_CANDIDATE_FACTORY_VERSION = "1.0"


def _selected_value(observation: CaptureObservation, field: str) -> Any:
    candidates = (observation.get("field_evidence") or {}).get(field) or []
    selected = [
        candidate
        for candidate in candidates
        if candidate.get("status") in {"selected", "derived"} and candidate.get("value") is not None
    ]
    values = {str(candidate.get("value")) for candidate in selected}
    return deepcopy(selected[0].get("value")) if len(values) == 1 else None


def food_candidate_from_observation(
    observation: CaptureObservation,
    *,
    meal_type: str = "snacks",
) -> dict[str, Any]:
    """Normalize any capture channel into the existing editable FoodCandidate shape."""
    errors = capture_observation_errors(observation)
    if errors:
        raise ValueError("Invalid CaptureObservation: " + "; ".join(errors))
    suggested_name = str(observation.get("suggested_name") or "").strip()
    display_name = suggested_name or "ラベルから追加した食品"
    candidate = unknown_candidate(display_name, meal_type)
    candidate["candidate_id"] = f"food_candidate_{observation['observation_id']}"
    candidate["canonical_name"] = suggested_name or None
    candidate["display_name"] = display_name
    candidate["raw_text"] = suggested_name or display_name
    candidate["size"] = _selected_value(observation, "size")
    candidate["nutrition"] = {
        "basis": _selected_value(observation, "basis") or "unknown",
        **{field: _selected_value(observation, field) for field in NUTRITION_FIELDS},
    }
    candidate.update(
        {
            "source_type": "unknown",
            "source_metadata": None,
            "source_label": "不明",
            "source_detail": "OCR抽出値（未確認）",
            "confidence": "low",
            "confirmed": False,
            "needs_review": True,
            "origin": "capture",
            "capture_metadata": {
                "contract_version": observation.get("contract_version"),
                "factory_version": FOOD_CANDIDATE_FACTORY_VERSION,
                "observation_id": observation.get("observation_id"),
                "capture_channel": observation.get("capture_channel"),
                "provider": observation.get("provider"),
                "provider_version": observation.get("provider_version"),
                "image_sha256": observation.get("image_sha256"),
                "raw_text": observation.get("raw_text"),
                "field_evidence": deepcopy(observation.get("field_evidence") or {}),
                "identifiers": deepcopy(observation.get("identifiers") or []),
                "warnings": deepcopy(observation.get("warnings") or []),
                "extraction_confidence": observation.get("extraction_confidence"),
            },
        }
    )
    return candidate


__all__ = ["FOOD_CANDIDATE_FACTORY_VERSION", "food_candidate_from_observation"]
