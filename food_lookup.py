from __future__ import annotations

from copy import deepcopy
import datetime as dt
import json
from pathlib import Path
from typing import Any

from food_aliases import normalize_food_name
from food_source_models import normalize_source_metadata, source_metadata_errors
from food_source_policy import select_nutrition_source


FOOD_LOOKUP_VERSION = "1.1"
CATALOG_PATH = Path(__file__).with_name("food_lookup_catalog.json")
VALID_BASES = {"per_item", "per_package", "per_serving", "per_100g", "per_100ml", "total", "unknown"}
NUTRITION_FIELDS = ("calories_kcal", "protein_g", "fat_g", "carbs_g", "sugar_g", "fiber_g", "salt_g")
ITEM_UNITS = {"個", "本", "枚", "切れ", "粒"}
PACKAGE_UNITS = {"パック", "袋", "缶"}
SERVING_UNITS = {"人前", "食", "皿", "杯"}


def _key(value: Any) -> str:
    return normalize_food_name(value).lower()


def _compact_key(value: Any) -> str:
    return _key(value).replace(" ", "")


def _parse_date(value: Any) -> dt.date | None:
    if value in {None, ""}:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _nutrition_is_valid(nutrition: Any) -> bool:
    if (
        not isinstance(nutrition, dict)
        or "basis" not in nutrition
        or any(field not in nutrition for field in NUTRITION_FIELDS)
        or nutrition.get("basis") not in VALID_BASES
    ):
        return False
    for field in NUTRITION_FIELDS:
        value = nutrition.get(field)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
            return False
    return True


def _catalog_identity(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _key(item.get("brand")),
        _key(item.get("canonical_name")),
        _key(item.get("variant")),
        _key(item.get("size")),
    )


def validate_catalog(catalog: Any) -> dict[str, Any]:
    """Validate catalog data and safely exclude invalid records from runtime use."""
    warnings: list[str] = []
    items = catalog if isinstance(catalog, list) else []
    valid_indexes: set[int] = set()
    item_ids: dict[str, list[int]] = {}
    active_identities: dict[tuple[str, str, str, str], list[int]] = {}

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            warnings.append(f"catalog[{index}]: record is not an object")
            continue
        source = item.get("source")
        valid_from = _parse_date(item.get("valid_from"))
        valid_to = _parse_date(item.get("valid_to"))
        if not item.get("id") or not item.get("category") or not item.get("canonical_name"):
            warnings.append(f"catalog[{index}]: missing required identity metadata")
            continue
        if any(field not in item for field in ("valid_from", "valid_to", "is_active")):
            warnings.append(f"catalog[{index}]: missing validity metadata")
            continue
        if not isinstance(item.get("is_active"), bool):
            warnings.append(f"catalog[{index}]: is_active must be boolean")
            continue
        if item.get("valid_from") and valid_from is None or item.get("valid_to") and valid_to is None:
            warnings.append(f"catalog[{index}]: invalid validity date")
            continue
        if valid_from and valid_to and valid_from > valid_to:
            warnings.append(f"catalog[{index}]: invalid validity window")
            continue
        if not _nutrition_is_valid(item.get("nutrition")):
            warnings.append(f"catalog[{index}]: invalid nutrition")
            continue
        source_errors = source_metadata_errors(source, require_reference=True)
        if source_errors:
            warnings.append(f"catalog[{index}]: {'; '.join(source_errors)}")
            continue
        valid_indexes.add(index)
        item_ids.setdefault(str(item["id"]), []).append(index)
        if item["is_active"]:
            active_identities.setdefault(_catalog_identity(item), []).append(index)

    excluded_indexes: set[int] = set()
    for food_id, indexes in item_ids.items():
        if len(indexes) > 1:
            warnings.append(f"duplicate food_id: {food_id}")
            excluded_indexes.update(indexes)
    for identity, indexes in active_identities.items():
        if len(indexes) > 1:
            warnings.append(f"duplicate active identity: {identity}")
            excluded_indexes.update(indexes)

    return {
        "valid_items": [deepcopy(items[index]) for index in sorted(valid_indexes - excluded_indexes)],
        "warnings": warnings,
    }


def load_food_lookup_catalog() -> tuple[list[dict[str, Any]], list[str]]:
    """Load reviewed local data. Malformed records are excluded without crashing the app."""
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"food lookup catalog could not be loaded: {exc}"]
    items = payload.get("items", []) if isinstance(payload, dict) else []
    validation = validate_catalog(items)
    return validation["valid_items"], validation["warnings"]


FOOD_LOOKUP_CATALOG, CATALOG_WARNINGS = load_food_lookup_catalog()


def _original_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "brand": item.get("brand"),
        "canonical_name": item.get("canonical_name"),
        "variant": item.get("variant"),
        "size": item.get("size"),
        "quantity": item.get("quantity"),
        "unit": item.get("unit"),
        "original_fragment": item.get("original_fragment") or item.get("raw_text"),
    }


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    nutrition = candidate.get("nutrition") if isinstance(candidate.get("nutrition"), dict) else {}
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    return {
        "food_id": candidate.get("id"),
        "brand": candidate.get("brand"),
        "canonical_name": candidate.get("canonical_name"),
        "variant": candidate.get("variant"),
        "size": candidate.get("size"),
        "nutrition": {field: nutrition.get(field) for field in ("basis", *NUTRITION_FIELDS)},
        "source_type": source.get("source_type"),
    }


def _result(
    item: dict[str, Any],
    *,
    status: str,
    match_type: str = "unresolved",
    confidence: str = "low",
    needs_review: bool = True,
    reason: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
    candidate: dict[str, Any] | None = None,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    original_identity = _original_identity(item)
    matched = status == "matched"
    return {
        "metadata": {"food_lookup_version": FOOD_LOOKUP_VERSION},
        "status": status,
        "matched": matched,
        "match_type": match_type,
        "confidence": confidence,
        "needs_review": needs_review,
        "candidates": candidates or [],
        "match": {"strategy": match_type, "confidence": confidence, "reason": reason},
        "food": (
            {
                "id": candidate["id"],
                "brand": candidate.get("brand"),
                "canonical_name": candidate.get("canonical_name"),
                "variant": candidate.get("variant"),
                "size": candidate.get("size"),
            }
            if candidate is not None
            else None
        ),
        "nutrition": deepcopy(candidate.get("nutrition")) if candidate is not None else None,
        "source": normalize_source_metadata(candidate.get("source")) if candidate is not None else None,
        "source_selection": (
            select_nutrition_source(
                [{"source": candidate.get("source"), "nutrition": candidate.get("nutrition")}], as_of=as_of
            )
            if candidate is not None
            else None
        ),
        "original_identity": original_identity,
        "input": original_identity,
    }


def _has_explicit_nutrition(item: dict[str, Any]) -> bool:
    nutrition = item.get("explicit_nutrition")
    return isinstance(nutrition, dict) and any(
        nutrition.get(field) is not None for field in ("calories_kcal", "protein_g", "fat_g", "carbs_g")
    )


def _is_eligible(candidate: dict[str, Any], as_of: dt.date) -> bool:
    if not candidate.get("is_active", False):
        return False
    valid_from = _parse_date(candidate.get("valid_from"))
    valid_to = _parse_date(candidate.get("valid_to"))
    if candidate.get("valid_from") and valid_from is None or candidate.get("valid_to") and valid_to is None:
        return False
    return (valid_from is None or valid_from <= as_of) and (valid_to is None or as_of <= valid_to)


def _catalog_match(item: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, str] | None:
    input_name = item.get("canonical_name") or item.get("name") or item.get("raw_text")
    input_key = _key(input_name)
    input_compact = _compact_key(input_name)
    aliases = [candidate.get("canonical_name"), *(candidate.get("aliases") or [])]
    exact_aliases = {_key(alias) for alias in aliases if _key(alias)}
    compact_aliases = {_compact_key(alias) for alias in aliases if _compact_key(alias)}
    if input_key not in exact_aliases and input_compact not in compact_aliases:
        return None
    if candidate.get("variant") != item.get("variant"):
        return None
    if candidate.get("size") is not None and candidate.get("size") != item.get("size"):
        return None

    input_brand = _key(item.get("brand"))
    candidate_brands = {_key(candidate.get("brand")), *(_key(alias) for alias in candidate.get("brand_aliases") or [])}
    if input_brand and input_brand not in candidate_brands:
        return None
    if input_brand:
        return ("brand_exact", "high")
    if input_key in exact_aliases:
        return ("canonical_exact", "high")
    return ("normalized_exact", "medium")


def lookup_food(
    item: dict[str, Any],
    *,
    catalog: list[dict[str, Any]] | None = None,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    """Resolve a parsed food without mutating it or fetching public data at runtime."""
    if not isinstance(item, dict):
        return _result({}, status="not_found", reason="invalid_item")
    if _has_explicit_nutrition(item):
        return _result(
            item,
            status="skipped_explicit_nutrition",
            match_type="explicit_nutrition",
            confidence="high",
            needs_review=False,
            reason="explicit_nutrition_has_priority",
        )

    today = as_of or dt.date.today()
    source_catalog = FOOD_LOOKUP_CATALOG if catalog is None else catalog
    matches: list[tuple[str, str, dict[str, Any]]] = []
    for candidate in source_catalog:
        if not isinstance(candidate, dict) or not _is_eligible(candidate, today):
            continue
        matched = _catalog_match(item, candidate)
        if matched:
            matches.append((matched[0], matched[1], candidate))
    if not matches:
        return _result(item, status="not_found", reason="not_found")
    if len(matches) > 1:
        return _result(
            item,
            status="ambiguous",
            reason="ambiguous_catalog_match",
            candidates=[_candidate_summary(candidate) for _, _, candidate in matches],
        )

    match_type, confidence, candidate = matches[0]
    return _result(
        item,
        status="matched",
        match_type=match_type,
        confidence=confidence,
        needs_review=False,
        candidate=candidate,
        as_of=today,
    )


def _numeric_quantity(quantity: Any) -> float | None:
    if isinstance(quantity, bool):
        return None
    try:
        value = float(quantity)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def calculate_lookup_total(lookup_result: dict[str, Any], quantity: Any, unit: Any) -> dict[str, Any]:
    """Apply a lookup nutrition basis to a parsed quantity without guessing units."""
    nutrition = lookup_result.get("nutrition") if isinstance(lookup_result, dict) else None
    if not isinstance(lookup_result, dict) or not lookup_result.get("matched") or not isinstance(nutrition, dict):
        return {"total_nutrition": None, "calories_kcal": None, "needs_review": True, "reason": "lookup_not_matched"}

    basis = nutrition.get("basis")
    amount = _numeric_quantity(quantity)
    normalized_unit = str(unit or "").lower()
    factor: float | None = None
    if basis == "per_item":
        factor = 1.0 if amount is None and not normalized_unit else amount if normalized_unit in ITEM_UNITS else None
    elif basis == "per_package":
        factor = 1.0 if amount is None and not normalized_unit else amount if normalized_unit in PACKAGE_UNITS else None
    elif basis == "per_serving":
        factor = 1.0 if amount is None and not normalized_unit else amount if normalized_unit in SERVING_UNITS else None
    elif basis == "per_100g":
        factor = amount / 100 if amount is not None and normalized_unit == "g" else None
    elif basis == "per_100ml":
        factor = amount / 100 if amount is not None and normalized_unit == "ml" else None
    elif basis == "total":
        factor = 1.0 if amount in {None, 1.0} and not normalized_unit else None

    if factor is None:
        return {
            "total_nutrition": None,
            "calories_kcal": None,
            "needs_review": True,
            "reason": "incompatible_or_unknown_quantity_unit",
        }

    total_nutrition = {
        field: (round(float(nutrition[field]) * factor, 4) if nutrition.get(field) is not None else None)
        for field in NUTRITION_FIELDS
    }
    return {
        "total_nutrition": total_nutrition,
        "calories_kcal": total_nutrition["calories_kcal"],
        "needs_review": False,
        "reason": None,
        "basis": basis,
        "factor": factor,
    }


def lookup_parsed_foods(parsed_foods: dict[str, Any]) -> dict[str, Any]:
    """Look up parser output and return a new result object without mutation."""
    items = parsed_foods.get("items", []) if isinstance(parsed_foods, dict) else []
    results = [lookup_food(item) for item in items if isinstance(item, dict)]
    return {
        "metadata": {"food_lookup_version": FOOD_LOOKUP_VERSION},
        "items": results,
        "matched_count": sum(result["matched"] for result in results),
        "unmatched_count": sum(not result["matched"] for result in results),
    }
