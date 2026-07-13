from __future__ import annotations

from copy import deepcopy
import datetime as dt
from typing import Any


SOURCE_METADATA_FIELDS = (
    "source_id",
    "source_type",
    "publisher",
    "source_ref",
    "captured_at",
    "verified_at",
    "valid_from",
    "valid_to",
    "product_version",
    "reviewer",
    "verification_status",
    "confidence",
    "notes",
)
SOURCE_TYPES = {
    "explicit_user_label",
    "official_product_page",
    "official_nutrition_table",
    "official_api_or_catalog",
    "bodyos_verified",
    "user_verified",
    "general_reference",
    "legacy_dictionary",
    "fallback_estimate",
}
VERIFICATION_STATUSES = {"verified", "pending_review", "rejected", "expired", "superseded"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}


def parse_source_date(value: Any) -> dt.date | None:
    if value in {None, ""}:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def normalize_source_metadata(source: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy with the shared contract keys present and no input mutation."""
    source = source if isinstance(source, dict) else {}
    normalized = {field: deepcopy(source.get(field)) for field in SOURCE_METADATA_FIELDS}
    if normalized["source_ref"] is None and source.get("url"):
        normalized["source_ref"] = str(source["url"])
    if normalized["verified_at"] is None and source.get("verified_on"):
        normalized["verified_at"] = str(source["verified_on"])
    return normalized


def source_metadata_errors(source: dict[str, Any] | None, *, require_reference: bool = False) -> list[str]:
    if not isinstance(source, dict):
        return ["source is not an object"]
    missing_fields = [field for field in SOURCE_METADATA_FIELDS if field not in source]
    if missing_fields:
        return [f"missing source fields: {', '.join(missing_fields)}"]
    errors: list[str] = []
    if not source.get("source_id"):
        errors.append("missing source_id")
    if source.get("source_type") not in SOURCE_TYPES:
        errors.append("invalid source_type")
    if source.get("verification_status") not in VERIFICATION_STATUSES:
        errors.append("invalid verification_status")
    if source.get("confidence") not in CONFIDENCE_LEVELS:
        errors.append("invalid source confidence")
    if require_reference and (not source.get("publisher") or not source.get("source_ref")):
        errors.append("missing source reference")
    for field in ("captured_at", "verified_at", "valid_from", "valid_to"):
        if source.get(field) is not None and parse_source_date(source[field]) is None:
            errors.append(f"invalid {field}")
    valid_from = parse_source_date(source.get("valid_from"))
    valid_to = parse_source_date(source.get("valid_to"))
    if valid_from and valid_to and valid_from > valid_to:
        errors.append("invalid source validity window")
    return errors


def explicit_user_label_source(*, captured_at: str | None = None, notes: str | None = None) -> dict[str, Any]:
    """Create source metadata for nutrition explicitly supplied by the user."""
    return {
        "source_id": "explicit-user-label",
        "source_type": "explicit_user_label",
        "publisher": "user",
        "source_ref": None,
        "captured_at": captured_at,
        "verified_at": None,
        "valid_from": None,
        "valid_to": None,
        "product_version": None,
        "reviewer": None,
        "verification_status": "pending_review",
        "confidence": "high",
        "notes": notes or "Nutrition explicitly supplied in meal text.",
    }


def internal_nutrition_source(source_type: str, source_id: str, *, notes: str | None = None) -> dict[str, Any]:
    """Create metadata for legacy dictionary and fallback results without claiming verification."""
    return {
        "source_id": source_id,
        "source_type": source_type,
        "publisher": "BodyOS",
        "source_ref": None,
        "captured_at": None,
        "verified_at": None,
        "valid_from": None,
        "valid_to": None,
        "product_version": None,
        "reviewer": None,
        "verification_status": "pending_review",
        "confidence": "medium" if source_type == "legacy_dictionary" else "low",
        "notes": notes,
    }
