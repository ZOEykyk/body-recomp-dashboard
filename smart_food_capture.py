from __future__ import annotations

from copy import deepcopy
import datetime as dt
import hashlib
import json
from typing import Any
from uuid import uuid4

from food_aliases import normalize_food_name
from food_lookup import NUTRITION_FIELDS, calculate_lookup_total
from food_source_policy import select_nutrition_source
from schema_contract import canonical_record_for_json, normalize_compatibility_record, validate_schema_record
from workout_intelligence import parse_workout_detail


SMART_FOOD_CAPTURE_VERSION = "1.0"
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snacks", "drinks")
MEAL_LABELS = {
    "breakfast": "朝",
    "lunch": "昼",
    "dinner": "夜",
    "snacks": "間食",
    "drinks": "ドリンク",
}
SOURCE_PRESENTATION = {
    "user_label": {"label": "確定", "detail": "今回の商品ラベル確認値", "confidence": "high"},
    "personal_master": {"label": "確定", "detail": "過去の確認値", "confidence": "high"},
    "official": {"label": "確定", "detail": "公式情報", "confidence": "high"},
    "trusted_catalog": {"label": "参考", "detail": "信頼済みカタログ", "confidence": "medium"},
    "estimated": {"label": "推定", "detail": "概算値", "confidence": "low"},
    "unknown": {"label": "不明", "detail": "栄養値未確認", "confidence": "low"},
}


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _positive_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def normalize_capture_unit(value: Any) -> str | None:
    text = str(value or "").strip()
    aliases = {"mL": "ml", "ML": "ml", "ｇ": "g", "ｍｌ": "ml"}
    return aliases.get(text, text) or None


def default_capture_nutrition_basis(unit: Any) -> str:
    """Return the deterministic basis used by the UI's per-unit nutrition fields."""
    normalized_unit = normalize_capture_unit(unit)
    if normalized_unit == "g":
        return "per_100g"
    if normalized_unit == "ml":
        return "per_100ml"
    return "per_item"


def _nutrition(value: Any, *, basis: str = "unknown") -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "basis": str(source.get("basis") or basis),
        **{field: _number(source.get(field)) for field in NUTRITION_FIELDS},
    }


def _compact(value: Any) -> str:
    return normalize_food_name(value).lower().replace(" ", "")


def _recency_rank(value: Any) -> float:
    try:
        return -dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _display_name(food: dict[str, Any]) -> str:
    parts = [food.get("brand"), food.get("canonical_name"), food.get("variant"), food.get("size")]
    normalized: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return " ".join(normalized) or "名称未設定"


def source_presentation(source_type: str) -> dict[str, str]:
    return deepcopy(SOURCE_PRESENTATION.get(source_type, SOURCE_PRESENTATION["unknown"]))


def _candidate_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"food_candidate_{hashlib.sha256(encoded).hexdigest()[:16]}"


def _origin_source_type(origin: str, *, accept_estimate: bool = False) -> str:
    return {
        "explicit": "user_label",
        "personal": "personal_master",
        "official": "official",
        "generic": "trusted_catalog",
        "fallback": "estimated" if accept_estimate else "unknown",
    }.get(origin, "unknown")


def _candidate_from_selected(
    item: dict[str, Any],
    selected: dict[str, Any] | None,
    *,
    origin: str,
    meal_type: str,
    accept_estimate: bool = False,
) -> dict[str, Any]:
    selected = selected if isinstance(selected, dict) else {}
    food = selected.get("food") if isinstance(selected.get("food"), dict) else {}
    source_type = _origin_source_type(origin, accept_estimate=accept_estimate)
    raw_nutrition = selected.get("nutrition") if source_type != "unknown" else None
    nutrition = _nutrition(raw_nutrition, basis="unknown")
    if source_type == "unknown":
        nutrition = _nutrition(None)
    name = str(
        food.get("canonical_name")
        or item.get("canonical_name")
        or item.get("original_fragment")
        or item.get("raw_text")
        or ""
    ).strip()
    identity = {
        "brand": food.get("brand") or item.get("brand"),
        "canonical_name": name,
        "variant": food.get("variant") or item.get("variant"),
        "size": food.get("size") or item.get("size"),
    }
    presentation = source_presentation(source_type)
    quantity = _positive_number(item.get("quantity")) or 1.0
    unit = normalize_capture_unit(item.get("unit") or food.get("default_unit"))
    payload = {
        "identity": identity,
        "origin": origin,
        "source_type": source_type,
        "nutrition": nutrition,
    }
    return {
        "candidate_id": _candidate_id(payload),
        "food_id": food.get("food_id") or food.get("id"),
        **identity,
        "display_name": _display_name(identity),
        "raw_text": item.get("original_fragment") or item.get("raw_text") or name,
        "meal_type": meal_type if meal_type in MEAL_TYPES else "snacks",
        "quantity": quantity,
        "unit": unit,
        "nutrition": nutrition,
        "source_type": source_type,
        "source_metadata": deepcopy(selected.get("source")),
        "source_label": presentation["label"],
        "source_detail": presentation["detail"],
        "confidence": presentation["confidence"],
        "confirmed": source_type in {"user_label", "personal_master", "official"},
        "needs_review": source_type in {"estimated", "unknown"},
        "origin": origin,
    }


def candidates_from_resolution(
    resolution: dict[str, Any],
    meal_type: str,
    *,
    accept_fallback_estimate: bool = False,
) -> list[dict[str, Any]]:
    """Convert Food Resolver output into editable candidates without mutating it."""
    candidates: list[dict[str, Any]] = []
    for result in (resolution or {}).get("items") or []:
        if not isinstance(result, dict):
            continue
        origin = str(result.get("selected_origin") or "fallback")
        candidates.append(
            _candidate_from_selected(
                deepcopy(result.get("item") or {}),
                deepcopy(result.get("selected") or {}),
                origin=origin,
                meal_type=meal_type,
                accept_estimate=accept_fallback_estimate,
            )
        )
    return candidates


def unknown_candidate(name: str, meal_type: str = "snacks") -> dict[str, Any]:
    item = {"canonical_name": str(name or "").strip(), "original_fragment": str(name or "").strip(), "quantity": 1}
    return _candidate_from_selected(item, None, origin="fallback", meal_type=meal_type, accept_estimate=False)


def _suggestion_from_personal(food: dict[str, Any]) -> dict[str, Any] | None:
    selection = select_nutrition_source(food.get("nutrition_sources") or [])
    selected = selection.get("selected") or {}
    if not selected:
        return None
    item = {
        "canonical_name": food.get("canonical_name"),
        "brand": food.get("brand"),
        "variant": food.get("variant"),
        "size": food.get("size"),
        "quantity": food.get("default_quantity") or 1,
        "unit": food.get("default_unit"),
    }
    candidate = _candidate_from_selected(
        item,
        {"food": food, "source": selected.get("source"), "nutrition": selected.get("nutrition")},
        origin="personal",
        meal_type="snacks",
    )
    candidate["aliases"] = deepcopy(food.get("aliases") or [])
    candidate["usage_count"] = max(int(food.get("usage_count") or 0), int(food.get("use_count") or 0))
    candidate["last_used_at"] = food.get("last_used_at")
    return candidate


def _suggestion_from_catalog(food: dict[str, Any], origin: str) -> dict[str, Any]:
    item = {
        "canonical_name": food.get("canonical_name"),
        "brand": food.get("brand"),
        "variant": food.get("variant"),
        "size": food.get("size"),
        "quantity": 1,
        "unit": None,
    }
    selected = {
        "food": food,
        "source": food.get("source"),
        "nutrition": food.get("nutrition"),
    }
    candidate = _candidate_from_selected(item, selected, origin=origin, meal_type="snacks")
    candidate["aliases"] = deepcopy(food.get("aliases") or [])
    candidate["usage_count"] = 0
    candidate["last_used_at"] = None
    return candidate


def search_food_candidates(
    query: str,
    knowledge: dict[str, Any],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return Personal/Frequent/Recent/Official/Generic suggestions in deterministic order."""
    needle = _compact(query)
    if not needle:
        return []
    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for food in deepcopy((knowledge or {}).get("personal_foods") or []):
        if food.get("status") != "active":
            continue
        values = [food.get("canonical_name"), *(food.get("aliases") or [])]
        keys = [_compact(value) for value in values if _compact(value)]
        if not any(needle in key for key in keys):
            continue
        candidate = _suggestion_from_personal(food)
        if candidate is None:
            continue
        usage = int(candidate.get("usage_count") or 0)
        recent = str(candidate.get("last_used_at") or "")
        candidate["rank_reason"] = "frequently_used" if usage > 0 else "personal_master"
        ranked.append(((0, -usage, _recency_rank(recent), candidate["display_name"]), candidate))

    for origin, foods, tier in (
        ("official", (knowledge or {}).get("official_catalog") or [], 3),
        ("generic", (knowledge or {}).get("generic_catalog") or [], 4),
    ):
        for food in deepcopy(foods):
            values = [food.get("canonical_name"), *(food.get("aliases") or [])]
            if not any(needle in _compact(value) for value in values if _compact(value)):
                continue
            candidate = _suggestion_from_catalog(food, origin)
            candidate["rank_reason"] = origin
            ranked.append(((tier, 0, 0.0, candidate["display_name"]), candidate))

    ranked.sort(key=lambda value: value[0])
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for _, candidate in ranked:
        identity = tuple(
            _compact(candidate.get(field)) for field in ("brand", "canonical_name", "variant", "size")
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(candidate)
        if len(unique) >= max(int(limit), 0):
            break
    return unique


def prepare_capture_item(
    candidate: dict[str, Any],
    *,
    meal_type: str,
    quantity: Any,
    unit: Any,
    consumed_quantity: Any,
    nutrition: dict[str, Any] | None = None,
    source_mode: str = "candidate",
    notes: str | None = None,
    capture_id: str | None = None,
) -> dict[str, Any]:
    """Create an editable capture item; source changes are explicit and deterministic."""
    prepared = deepcopy(candidate)
    prepared["capture_id"] = capture_id or f"capture_{uuid4().hex}"
    prepared["meal_type"] = meal_type if meal_type in MEAL_TYPES else "snacks"
    prepared["quantity"] = _positive_number(quantity) or 1.0
    prepared["unit"] = normalize_capture_unit(unit)
    consumed = _number(consumed_quantity) or 0.0
    prepared["consumed_quantity"] = min(max(consumed, 0.0), prepared["quantity"])
    if prepared["consumed_quantity"] <= 0:
        prepared["consumption_status"] = "planned"
    elif prepared["consumed_quantity"] < prepared["quantity"]:
        prepared["consumption_status"] = "partially_consumed"
    else:
        prepared["consumption_status"] = "consumed"
    prepared["notes"] = str(notes or "").strip() or None

    original_nutrition = _nutrition(candidate.get("nutrition"))
    edited_nutrition = _nutrition(nutrition if nutrition is not None else original_nutrition)
    changed = edited_nutrition != original_nutrition
    if not any(edited_nutrition.get(field) is not None for field in NUTRITION_FIELDS):
        source_type = "unknown"
    elif source_mode == "user_label":
        source_type = "user_label"
    elif source_mode == "estimated" or changed:
        source_type = "estimated"
    else:
        source_type = str(candidate.get("source_type") or "unknown")
    if (
        edited_nutrition.get("basis") == "unknown"
        and source_type in {"user_label", "estimated"}
        and any(edited_nutrition.get(field) is not None for field in NUTRITION_FIELDS)
    ):
        edited_nutrition["basis"] = default_capture_nutrition_basis(prepared["unit"])
    presentation = source_presentation(source_type)
    prepared.update(
        {
            "nutrition": edited_nutrition,
            "source_type": source_type,
            "source_label": presentation["label"],
            "source_detail": presentation["detail"],
            "confidence": presentation["confidence"],
            "confirmed": source_type in {"user_label", "personal_master", "official"},
            "needs_review": source_type in {"estimated", "unknown"},
            "edited": changed,
        }
    )
    return prepared


def calculate_capture_item_total(item: dict[str, Any]) -> dict[str, Any]:
    """Scale one captured food using consumed quantity only."""
    if not isinstance(item, dict) or _number(item.get("consumed_quantity")) in (None, 0):
        return {"included": False, "total_nutrition": None, "needs_review": False, "reason": "not_consumed"}
    nutrition = _nutrition(item.get("nutrition"))
    if not any(nutrition.get(field) is not None for field in NUTRITION_FIELDS):
        return {"included": True, "total_nutrition": None, "needs_review": True, "reason": "nutrition_unknown"}

    consumed_quantity = _positive_number(item.get("consumed_quantity"))
    unit = normalize_capture_unit(item.get("unit"))
    if nutrition.get("basis") == "total":
        if consumed_quantity == _positive_number(item.get("quantity")):
            return {"included": True, "total_nutrition": nutrition, "needs_review": False, "reason": None, "factor": 1.0}
        return {"included": True, "total_nutrition": None, "needs_review": True, "reason": "partial_total_cannot_scale"}
    result = calculate_lookup_total(
        {"matched": True, "nutrition": nutrition},
        consumed_quantity,
        unit,
    )
    return {"included": True, **result}


def calculate_daily_nutrition(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Aggregate unique consumed foods and keep unknown items separate from zero kcal."""
    totals = {field: 0.0 for field in NUTRITION_FIELDS}
    known_counts = {field: 0 for field in NUTRITION_FIELDS}
    consumed_count = 0
    unknown_items: list[str] = []
    included: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in deepcopy(items or []):
        capture_id = str(item.get("capture_id") or _candidate_id(item))
        if capture_id in seen:
            continue
        seen.add(capture_id)
        result = calculate_capture_item_total(item)
        if not result.get("included"):
            continue
        consumed_count += 1
        total = result.get("total_nutrition")
        if not isinstance(total, dict) or total.get("calories_kcal") is None:
            unknown_items.append(str(item.get("display_name") or item.get("canonical_name") or item.get("raw_text") or "不明食品"))
        if isinstance(total, dict):
            for field in NUTRITION_FIELDS:
                value = _number(total.get(field))
                if value is not None:
                    totals[field] += value
                    known_counts[field] += 1
        included.append({"item": item, "calculation": result})
    rounded = {
        field: (round(value, 2) if known_counts[field] else 0.0 if consumed_count == 0 else None)
        for field, value in totals.items()
    }
    coverage = round(known_counts["calories_kcal"] / consumed_count * 100) if consumed_count else 0
    return {
        "totals": rounded,
        "known_counts": known_counts,
        "consumed_count": consumed_count,
        "unknown_count": len(unknown_items),
        "unknown_items": unknown_items,
        "known_coverage_percent": coverage,
        "included_items": included,
    }


def _canonical_meal_item(item: dict[str, Any], calculation: dict[str, Any]) -> dict[str, Any]:
    total = calculation.get("total_nutrition")
    nutrition = (
        {"basis": "total", **{field: _number(total.get(field)) for field in NUTRITION_FIELDS if field in {"calories_kcal", "protein_g", "fat_g", "carbs_g"}}}
        if isinstance(total, dict)
        else {"basis": "unknown", "calories_kcal": None, "protein_g": None, "fat_g": None, "carbs_g": None}
    )
    source_note = f"source={item.get('source_type', 'unknown')}; confidence={item.get('confidence', 'low')}"
    notes = " / ".join(value for value in [str(item.get("notes") or "").strip(), source_note] if value)
    return {
        "name": str(item.get("display_name") or item.get("canonical_name") or item.get("raw_text") or "不明食品"),
        "quantity": _positive_number(item.get("consumed_quantity")),
        "unit": normalize_capture_unit(item.get("unit")),
        "notes": notes,
        "nutrition": nutrition,
    }


def build_canonical_daily_record(daily: dict[str, Any], items: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Build Canonical Schema 1.0 from UI state without mutating either input."""
    aggregate = calculate_daily_nutrition(items)
    meals = {meal_type: [] for meal_type in MEAL_TYPES}
    for included in aggregate["included_items"]:
        item = included["item"]
        meal_type = str(item.get("meal_type") or "snacks")
        if meal_type not in meals:
            meal_type = "snacks"
        meals[meal_type].append(_canonical_meal_item(item, included["calculation"]))

    record = {
        "schema_version": "1.0",
        "date": str(daily.get("date") or dt.date.today().isoformat()),
        "weight": _positive_number(daily.get("weight")),
        "sleep": {"hours": _number(daily.get("sleep_hours"))},
        "condition": _number(daily.get("condition")),
        "steps": int(_number(daily.get("steps")) or 0),
        "meals": meals,
        "alcohol": {
            "consumed": bool(daily.get("alcohol_consumed")),
            "detail": str(daily.get("alcohol_detail") or "").strip() or None,
            "level": str(daily.get("alcohol_level") or "").strip() or None,
        },
        "workout": deepcopy(daily.get("workout")) if isinstance(daily.get("workout"), dict) else {"performed": False, "exercises": []},
        "notes": str(daily.get("notes") or "").strip() or None,
        "mode": str(daily.get("mode") or "NORMAL"),
        "event_name": str(daily.get("event_name") or "").strip() or None,
        "nutrition_totals": {
            "basis": "total",
            "calories_kcal": aggregate["totals"]["calories_kcal"],
            "protein_g": aggregate["totals"]["protein_g"],
            "fat_g": aggregate["totals"]["fat_g"],
            "carbs_g": aggregate["totals"]["carbs_g"],
        },
    }
    return canonical_record_for_json(record)


def canonical_builder_result(daily: dict[str, Any], items: list[dict[str, Any]] | None) -> dict[str, Any]:
    canonical = build_canonical_daily_record(daily, items)
    normalized, changes, normalization_issues = normalize_compatibility_record(canonical)
    issues = [*normalization_issues, *validate_schema_record(normalized)]
    return {
        "metadata": {"smart_food_capture_version": SMART_FOOD_CAPTURE_VERSION},
        "canonical": normalized,
        "validation_passed": not issues,
        "validation_issues": issues,
        "normalization_changes": changes,
        "nutrition": calculate_daily_nutrition(items),
    }


def captured_meal_texts(items: list[dict[str, Any]] | None) -> dict[str, str]:
    result = {meal_type: "" for meal_type in MEAL_TYPES}
    names: dict[str, list[str]] = {meal_type: [] for meal_type in MEAL_TYPES}
    for item in items or []:
        if (_number(item.get("consumed_quantity")) or 0) <= 0:
            continue
        meal_type = str(item.get("meal_type") or "snacks")
        if meal_type not in names:
            meal_type = "snacks"
        name = str(item.get("display_name") or item.get("canonical_name") or item.get("raw_text") or "").strip()
        if name:
            names[meal_type].append(name)
    return {meal_type: "、".join(values) for meal_type, values in names.items()}


def canonical_workout_from_text(performed: bool, text: str) -> dict[str, Any]:
    """Project the existing workout parser into the Canonical Schema 1.0 shape."""
    raw_text = str(text or "").strip()
    exercises: list[dict[str, Any]] = []
    if performed or raw_text:
        for parsed in parse_workout_detail(raw_text):
            if parsed.get("exercise") == "unknown":
                continue
            sets: list[dict[str, Any]] = []
            work_sets = parsed.get("work_sets") or []
            if work_sets:
                for group in work_sets:
                    for reps in group.get("reps") or []:
                        sets.append(
                            {
                                "weight_kg": _number(group.get("weight_kg")),
                                "reps": int(reps),
                                "completed": True,
                                "set_type": "work",
                            }
                        )
            else:
                for reps in parsed.get("reps") or []:
                    sets.append(
                        {
                            "weight_kg": None,
                            "reps": int(reps),
                            "completed": True,
                            "set_type": "work",
                        }
                    )
            exercises.append(
                {
                    "name": str(parsed.get("exercise")),
                    "equipment": None,
                    "notes": None,
                    "sets": sets,
                }
            )
    return {
        "performed": bool(performed or exercises),
        "program_name": None,
        "workout_type": None,
        "duration_minutes": None,
        "notes": raw_text or None,
        "exercises": exercises,
    }


__all__ = [
    "MEAL_LABELS",
    "MEAL_TYPES",
    "SMART_FOOD_CAPTURE_VERSION",
    "SOURCE_PRESENTATION",
    "build_canonical_daily_record",
    "canonical_workout_from_text",
    "calculate_capture_item_total",
    "calculate_daily_nutrition",
    "canonical_builder_result",
    "captured_meal_texts",
    "candidates_from_resolution",
    "normalize_capture_unit",
    "prepare_capture_item",
    "search_food_candidates",
    "source_presentation",
    "unknown_candidate",
]
