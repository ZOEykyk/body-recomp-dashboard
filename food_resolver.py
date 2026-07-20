from __future__ import annotations

from copy import deepcopy
import datetime as dt
from typing import Any

from food_knowledge_catalog import GENERIC_FOOD_CATALOG, match_generic_food
from food_lookup import FOOD_LOOKUP_CATALOG, NUTRITION_FIELDS, calculate_lookup_total, lookup_food
from food_parser import parse_food_text
from food_source_models import explicit_user_label_source, internal_nutrition_source
from food_source_policy import FOOD_SOURCE_POLICY_VERSION, select_food_resolution_candidate
from personal_food_master import personal_food_source_selection, resolve_personal_food


FOOD_RESOLVER_VERSION = "1.0"
MEAL_FALLBACK_KCAL = {
    "朝": 300,
    "breakfast": 300,
    "昼": 750,
    "lunch": 750,
    "夜": 850,
    "dinner": 850,
    "間食": 200,
    "snacks": 200,
    "仕事中のドリンク": 100,
    "work_drinks": 100,
}
ITEM_FALLBACK_KCAL = {
    "朝": 120,
    "breakfast": 120,
    "昼": 150,
    "lunch": 150,
    "夜": 150,
    "dinner": 150,
    "間食": 120,
    "snacks": 120,
    "仕事中のドリンク": 80,
    "work_drinks": 80,
}
RESOLUTION_ORIGINS = ("explicit", "personal", "official", "generic", "fallback")


def build_food_knowledge_snapshot(
    personal_foods: list[dict[str, Any]] | None = None,
    *,
    official_catalog: list[dict[str, Any]] | None = None,
    generic_catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an immutable-by-convention resolver input with no repository dependency."""
    return {
        "metadata": {
            "food_resolver_version": FOOD_RESOLVER_VERSION,
            "source_policy_version": FOOD_SOURCE_POLICY_VERSION,
        },
        "personal_foods": deepcopy(personal_foods or []),
        "official_catalog": deepcopy(FOOD_LOOKUP_CATALOG if official_catalog is None else official_catalog),
        "generic_catalog": deepcopy(GENERIC_FOOD_CATALOG if generic_catalog is None else generic_catalog),
    }


def _candidate(
    origin: str,
    source: dict[str, Any],
    nutrition: dict[str, Any],
    *,
    food: dict[str, Any] | None = None,
    confidence: str,
    needs_review: bool = False,
) -> dict[str, Any]:
    return {
        "origin": origin,
        "source": deepcopy(source),
        "nutrition": deepcopy(nutrition),
        "food": deepcopy(food),
        "confidence": confidence,
        "needs_review": needs_review,
        "usable": True,
    }


def _calculated_candidate(candidate: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    calculated = deepcopy(candidate)
    total = calculate_lookup_total(
        {"matched": True, "nutrition": calculated["nutrition"]},
        item.get("quantity"),
        item.get("unit"),
    )
    calculated["quantity_result"] = total
    calculated["total_nutrition"] = deepcopy(total.get("total_nutrition"))
    calculated["usable"] = not total.get("needs_review") and total.get("calories_kcal") is not None
    return calculated


def _explicit_candidate(nutrition: dict[str, Any]) -> dict[str, Any]:
    normalized = {field: nutrition.get(field) for field in NUTRITION_FIELDS}
    normalized["basis"] = nutrition.get("basis") or "unknown"
    return _candidate(
        "explicit",
        explicit_user_label_source(notes="Explicit nutrition extracted from the current meal text."),
        normalized,
        confidence="high",
    )


def _personal_candidates(item: dict[str, Any], foods: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    resolution = resolve_personal_food(item, foods)
    food = resolution.get("food")
    if food is None:
        return [], str(resolution.get("status") or "not_found")
    selection = personal_food_source_selection(food)
    selected = selection.get("selected") or {}
    if not selected:
        return [], "matched_without_nutrition"
    candidate = _candidate(
        "personal",
        selected.get("source") or {},
        selected.get("nutrition") or {},
        food=food,
        confidence="high" if not selection.get("needs_review") else "medium",
        needs_review=bool(selection.get("needs_review")),
    )
    return [_calculated_candidate(candidate, item)], "matched"


def _official_candidates(item: dict[str, Any], catalog: list[dict[str, Any]], as_of: dt.date) -> tuple[list[dict[str, Any]], str]:
    result = lookup_food(item, catalog=catalog, as_of=as_of)
    if not result.get("matched"):
        return [], str(result.get("status") or "not_found")
    candidate = _candidate(
        "official",
        result.get("source") or {},
        result.get("nutrition") or {},
        food=result.get("food"),
        confidence=str(result.get("confidence") or "high"),
        needs_review=bool(result.get("needs_review")),
    )
    return [_calculated_candidate(candidate, item)], "matched"


def _generic_candidates(item: dict[str, Any], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    match = match_generic_food(item, catalog)
    if match is None:
        return []
    candidate = _candidate(
        "generic",
        match["source"],
        match["nutrition"],
        food={
            "id": match.get("food_id"),
            "brand": match.get("brand"),
            "canonical_name": match.get("canonical_name"),
            "variant": match.get("variant"),
            "size": match.get("size"),
        },
        confidence="medium",
        needs_review=False,
    )
    quantity_item = item
    if match["nutrition"].get("basis") == "per_item" and item.get("unit") in {"g", "ml"}:
        quantity_item = deepcopy(item)
        quantity_item["quantity"] = 1
        quantity_item["unit"] = None
    return [_calculated_candidate(candidate, quantity_item)]


def _fallback_candidate(item: dict[str, Any], meal_type: str) -> dict[str, Any]:
    kcal = ITEM_FALLBACK_KCAL.get(meal_type, 120)
    nutrition = {field: None for field in NUTRITION_FIELDS}
    nutrition.update({"basis": "total", "calories_kcal": kcal})
    return _candidate(
        "fallback",
        internal_nutrition_source(
            "fallback_estimate",
            f"fallback-estimate:{meal_type or 'meal'}:{item.get('index', 0)}",
            notes="Fallback estimate for an unresolved food fragment.",
        ),
        nutrition,
        food={"canonical_name": item.get("canonical_name") or item.get("original_fragment")},
        confidence="low",
        needs_review=True,
    ) | {"total_nutrition": deepcopy(nutrition)}


def _resolve_item(item: dict[str, Any], knowledge: dict[str, Any], meal_type: str, as_of: dt.date) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    explicit = item.get("explicit_nutrition") or {}
    if any(explicit.get(field) is not None for field in ("calories_kcal", "protein_g", "fat_g", "carbs_g")):
        candidates.append(_explicit_candidate(explicit) | {"total_nutrition": deepcopy(explicit)})
    personal, personal_status = _personal_candidates(item, knowledge["personal_foods"])
    official, official_status = _official_candidates(item, knowledge["official_catalog"], as_of)
    candidates.extend(personal)
    candidates.extend(official)
    candidates.extend(_generic_candidates(item, knowledge["generic_catalog"]))
    candidates.append(_fallback_candidate(item, meal_type))
    selection = select_food_resolution_candidate(candidates, as_of=as_of)
    selected = selection.get("selected")
    return {
        "item": deepcopy(item),
        "status": "matched" if selected else "not_found",
        "selected_origin": selected.get("origin") if selected else None,
        "selected": deepcopy(selected),
        "source_selection": selection,
        "total_nutrition": deepcopy((selected or {}).get("total_nutrition")),
        "confidence": str((selected or {}).get("confidence") or "low"),
        "needs_review": bool(selection.get("needs_review")),
        "diagnostics": {"personal": personal_status, "official": official_status},
    }


def _meal_explicit_result(parsed: dict[str, Any], meal_type: str, as_of: dt.date) -> dict[str, Any]:
    explicit = deepcopy(parsed["explicit_nutrition"])
    candidate = _explicit_candidate(explicit) | {"total_nutrition": deepcopy(explicit)}
    selection = select_food_resolution_candidate([candidate], as_of=as_of)
    item_results = [
        {
            "item": deepcopy(item),
            "status": "matched",
            "selected_origin": "explicit",
            "selected": deepcopy(selection["selected"]),
            "source_selection": deepcopy(selection),
            "total_nutrition": deepcopy(explicit),
            "confidence": "high",
            "needs_review": False,
            "diagnostics": {"meal_level_explicit": True},
        }
        for item in parsed.get("items") or []
    ]
    calories = explicit.get("calories_kcal")
    return {
        "metadata": {"food_resolver_version": FOOD_RESOLVER_VERSION, "source_policy_version": FOOD_SOURCE_POLICY_VERSION},
        "meal_type": meal_type,
        "parsed_foods": parsed,
        "items": item_results,
        "meal_explicit": True,
        "total_nutrition": explicit,
        "kcal": int(round(float(calories or 0))),
        "confidence": "high",
        "detected_foods": [str(item.get("canonical_name") or item.get("original_fragment")) for item in parsed.get("items") or []] or ["explicit_kcal"],
        "unknown_items": [],
        "resolution_counts": {origin: (max(len(item_results), 1) if origin == "explicit" else 0) for origin in RESOLUTION_ORIGINS},
        "source_type_distribution": {"explicit_user_label": max(len(item_results), 1)},
        "nutrition_source_decisions": [selection],
    }


def _aggregate_nutrition(item_results: list[dict[str, Any]], calories: float) -> dict[str, Any]:
    totals: dict[str, Any] = {field: 0.0 for field in NUTRITION_FIELDS}
    complete = {field: True for field in NUTRITION_FIELDS}
    for result in item_results:
        nutrition = result.get("total_nutrition") or {}
        for field in NUTRITION_FIELDS:
            value = nutrition.get(field)
            if value is None:
                complete[field] = False
            else:
                totals[field] += float(value)
    totals["calories_kcal"] = calories
    for field in NUTRITION_FIELDS:
        if field != "calories_kcal" and not complete[field]:
            totals[field] = None
        elif totals[field] is not None:
            totals[field] = round(float(totals[field]), 4)
    totals["basis"] = "total"
    return totals


def resolve_food_text(
    text: str,
    meal_type: str | None = None,
    *,
    knowledge: dict[str, Any] | None = None,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    """Pure Food Knowledge resolution entry point used by every BodyOS consumer."""
    safe_knowledge = deepcopy(knowledge) if isinstance(knowledge, dict) else build_food_knowledge_snapshot()
    safe_knowledge.setdefault("personal_foods", [])
    safe_knowledge.setdefault("official_catalog", deepcopy(FOOD_LOOKUP_CATALOG))
    safe_knowledge.setdefault("generic_catalog", deepcopy(GENERIC_FOOD_CATALOG))
    normalized_meal_type = str(meal_type or "")
    parsed = parse_food_text(str(text or ""), meal_type=normalized_meal_type)
    date = as_of or dt.date.today()

    if parsed.get("is_zero_meal") or not str(text or "").strip():
        return {
            "metadata": {"food_resolver_version": FOOD_RESOLVER_VERSION, "source_policy_version": FOOD_SOURCE_POLICY_VERSION},
            "meal_type": normalized_meal_type,
            "parsed_foods": parsed,
            "items": [],
            "meal_explicit": False,
            "total_nutrition": {field: (0 if field == "calories_kcal" else None) for field in NUTRITION_FIELDS} | {"basis": "total"},
            "kcal": 0,
            "confidence": "high" if parsed.get("is_zero_meal") else "low",
            "detected_foods": ["zero_meal"] if parsed.get("is_zero_meal") else [],
            "unknown_items": [],
            "resolution_counts": {origin: 0 for origin in RESOLUTION_ORIGINS},
            "source_type_distribution": {},
            "nutrition_source_decisions": [],
        }

    explicit = parsed.get("explicit_nutrition") or {}
    if explicit.get("calories_kcal") is not None:
        return _meal_explicit_result(parsed, normalized_meal_type, date)

    item_results = [_resolve_item(item, safe_knowledge, normalized_meal_type, date) for item in parsed.get("items") or []]
    counts = {origin: 0 for origin in RESOLUTION_ORIGINS}
    sources: dict[str, int] = {}
    detected: list[str] = []
    unknown: list[str] = []
    calories = 0.0
    for result in item_results:
        origin = str(result.get("selected_origin") or "fallback")
        counts[origin] = counts.get(origin, 0) + 1
        selected = result.get("selected") or {}
        source_type = str((selected.get("source") or {}).get("source_type") or "fallback_estimate")
        sources[source_type] = sources.get(source_type, 0) + 1
        calories += float((result.get("total_nutrition") or {}).get("calories_kcal") or 0)
        fragment = str(result.get("item", {}).get("original_fragment") or "")
        if origin == "fallback":
            unknown.append(fragment)
        else:
            food = selected.get("food") or {}
            detected.append(str(food.get("canonical_name") or result.get("item", {}).get("canonical_name") or fragment))

    if item_results and counts["fallback"] == len(item_results) and normalized_meal_type in MEAL_FALLBACK_KCAL:
        calories = float(MEAL_FALLBACK_KCAL[normalized_meal_type])
    if counts["fallback"]:
        confidence = "medium" if len(item_results) > counts["fallback"] else "low"
    elif counts["generic"]:
        confidence = "medium"
    elif item_results:
        confidence = "high"
    else:
        confidence = "low"

    return {
        "metadata": {"food_resolver_version": FOOD_RESOLVER_VERSION, "source_policy_version": FOOD_SOURCE_POLICY_VERSION},
        "meal_type": normalized_meal_type,
        "parsed_foods": parsed,
        "items": item_results,
        "meal_explicit": False,
        "total_nutrition": _aggregate_nutrition(item_results, calories),
        "kcal": int(round(calories)),
        "confidence": confidence,
        "detected_foods": detected,
        "unknown_items": unknown,
        "resolution_counts": counts,
        "source_type_distribution": sources,
        "nutrition_source_decisions": [result["source_selection"] for result in item_results],
    }


def summarize_resolutions(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"encounter_count": 0, **{origin: 0 for origin in RESOLUTION_ORIGINS}}
    for result in results:
        for origin in RESOLUTION_ORIGINS:
            summary[origin] += int((result.get("resolution_counts") or {}).get(origin, 0))
    return summary


__all__ = [
    "FOOD_RESOLVER_VERSION",
    "RESOLUTION_ORIGINS",
    "build_food_knowledge_snapshot",
    "resolve_food_text",
    "summarize_resolutions",
]
