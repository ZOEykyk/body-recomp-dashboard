"""Shared constants and small pure helpers for Nutrition Intelligence."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


NUTRITION_INTELLIGENCE_VERSION = "1.0"
NUTRITION_RULESET_VERSION = "1.0"
SCORE_WEIGHTS = {
    "calories": 20,
    "protein": 20,
    "fat": 15,
    "carbs": 10,
    "fiber": 10,
    "salt": 10,
    "vegetables": 10,
    "hydration": 5,
}
METRIC_FIELDS = ("calories_kcal", "protein_g", "fat_g", "carbs_g", "fiber_g", "salt_g", "hydration_ml")
MEAL_COLUMNS = {
    "breakfast": ("朝", "breakfast"),
    "lunch": ("昼", "lunch"),
    "dinner": ("夜", "dinner"),
    "snacks": ("間食", "snacks", "snack"),
    "work_drinks": ("仕事中のドリンク", "work_drinks", "drinks"),
}


def as_positive_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def record_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def meal_texts(record: dict[str, Any]) -> dict[str, str]:
    copy = deepcopy(record)
    meals = copy.get("meals") if isinstance(copy.get("meals"), dict) else copy.get("食事")
    values: dict[str, str] = {}
    for meal_type, keys in MEAL_COLUMNS.items():
        value = record_value(copy, *keys)
        if value is None and isinstance(meals, dict):
            value = record_value(meals, *keys)
        values[meal_type] = str(value or "").strip()
    return values


def numeric_nutrition_from_record(record: dict[str, Any]) -> dict[str, float | None]:
    nested = record.get("nutrition") if isinstance(record.get("nutrition"), dict) else {}
    aliases = {
        "calories_kcal": ("calories_kcal", "calories", "推定摂取カロリー", "推定摂取カロリー(kcal)"),
        "protein_g": ("protein_g", "protein", "タンパク質g", "タンパク質"),
        "fat_g": ("fat_g", "fat", "脂質g", "脂質"),
        "carbs_g": ("carbs_g", "carbs", "炭水化物g", "炭水化物"),
        "fiber_g": ("fiber_g", "fiber", "食物繊維g", "食物繊維"),
        "salt_g": ("salt_g", "salt", "食塩相当量g", "塩分g"),
        "hydration_ml": ("hydration_ml", "water_ml", "水分ml", "水分"),
    }
    return {
        field: as_positive_number(record_value(nested, *keys) if record_value(nested, *keys) is not None else record_value(record, *keys))
        for field, keys in aliases.items()
    }
