from __future__ import annotations

from copy import deepcopy
import datetime as dt
from typing import Any

from food_source_models import (
    SOURCE_METADATA_FIELDS,
    explicit_user_label_source,
    normalize_source_metadata,
    parse_source_date,
    source_metadata_errors,
)


SOURCE_PRIORITY = {
    "explicit_user_label": 1,
    "official_product_page": 2,
    "official_nutrition_table": 3,
    "official_api_or_catalog": 4,
    "bodyos_verified": 5,
    "user_verified": 6,
    "general_reference": 7,
    "legacy_dictionary": 8,
    "fallback_estimate": 9,
}
STALE_AFTER_DAYS = {
    "official_product_page": 365,
    "official_nutrition_table": 365,
    "official_api_or_catalog": 180,
    "bodyos_verified": 180,
    "user_verified": 90,
    "general_reference": 365,
    "legacy_dictionary": 365,
    "fallback_estimate": 0,
}
NUTRITION_COMPARISON_FIELDS = ("calories_kcal", "protein_g", "fat_g", "carbs_g", "sugar_g", "fiber_g", "salt_g")


def source_priority(source_type: str) -> int:
    """Return the deterministic BodyOS source rank; lower is more authoritative."""
    return SOURCE_PRIORITY.get(str(source_type or ""), len(SOURCE_PRIORITY) + 1)


def is_source_current(source: dict[str, Any], as_of: dt.date | None = None) -> bool:
    metadata = normalize_source_metadata(source)
    date = as_of or dt.date.today()
    if metadata["verification_status"] in {"rejected", "expired", "superseded"}:
        return False
    valid_from = parse_source_date(metadata["valid_from"])
    valid_to = parse_source_date(metadata["valid_to"])
    return (valid_from is None or valid_from <= date) and (valid_to is None or date <= valid_to)


def is_source_fresh(source: dict[str, Any], as_of: dt.date | None = None) -> bool:
    metadata = normalize_source_metadata(source)
    source_type = metadata["source_type"]
    if source_type == "explicit_user_label":
        return True
    max_age = STALE_AFTER_DAYS.get(source_type)
    if max_age is None:
        return False
    reference_date = parse_source_date(metadata["verified_at"]) or parse_source_date(metadata["captured_at"])
    if reference_date is None:
        return False
    return ((as_of or dt.date.today()) - reference_date).days <= max_age


def _nutrition_fingerprint(nutrition: Any) -> tuple[Any, ...] | None:
    if not isinstance(nutrition, dict):
        return None
    return tuple(nutrition.get(field) for field in NUTRITION_COMPARISON_FIELDS)


def _candidate_summary(candidate: dict[str, Any], *, as_of: dt.date) -> dict[str, Any]:
    source = normalize_source_metadata(candidate.get("source"))
    return {
        "source": source,
        "nutrition": deepcopy(candidate.get("nutrition")),
        "priority": source_priority(source["source_type"]),
        "is_current": is_source_current(source, as_of),
        "is_fresh": is_source_fresh(source, as_of),
    }


def select_nutrition_source(candidates: list[dict[str, Any]] | None, *, as_of: dt.date | None = None) -> dict[str, Any]:
    """Select a source deterministically while preserving stale/conflicting evidence for review."""
    date = as_of or dt.date.today()
    evaluated: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        source = normalize_source_metadata(candidate.get("source"))
        if source_metadata_errors(source):
            continue
        evaluated.append(_candidate_summary(candidate, as_of=date))

    eligible = [candidate for candidate in evaluated if candidate["is_current"]]
    if not eligible:
        return {
            "status": "not_found",
            "selected": None,
            "reason": "no_current_valid_source",
            "needs_review": True,
            "conflict": False,
            "candidates": evaluated,
        }

    eligible.sort(key=lambda candidate: (candidate["priority"], not candidate["is_fresh"], candidate["source"]["source_id"]))
    top_priority = eligible[0]["priority"]
    top_candidates = [candidate for candidate in eligible if candidate["priority"] == top_priority]
    top_fingerprints = {_nutrition_fingerprint(candidate["nutrition"]) for candidate in top_candidates}
    if len(top_candidates) > 1 and len(top_fingerprints) > 1:
        return {
            "status": "conflict",
            "selected": None,
            "reason": "same_priority_nutrition_conflict",
            "needs_review": True,
            "conflict": True,
            "candidates": eligible,
        }

    selected = top_candidates[0]
    all_fingerprints = {_nutrition_fingerprint(candidate["nutrition"]) for candidate in eligible}
    conflict = len(all_fingerprints) > 1
    selected_pending_review = (
        selected["source"]["verification_status"] != "verified"
        and selected["source"]["source_type"] != "explicit_user_label"
    )
    return {
        "status": "selected_with_conflict" if conflict else "selected",
        "selected": selected,
        "reason": "higher_priority_source" if conflict else "highest_priority_current_source",
        "needs_review": conflict or not selected["is_fresh"] or selected_pending_review,
        "conflict": conflict,
        "candidates": eligible,
    }


__all__ = [
    "SOURCE_METADATA_FIELDS",
    "explicit_user_label_source",
    "is_source_current",
    "is_source_fresh",
    "select_nutrition_source",
    "source_priority",
]
