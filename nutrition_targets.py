"""Centralized, conservative defaults for Nutrition Intelligence v1."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


NUTRITION_TARGET_VERSION = "1.0"
DEFAULTS = {
    "calorie_target": 2200.0,
    "protein_g_per_kg": 1.6,
    "protein_default_g": 120.0,
    "fat_calorie_ratio_min": 0.25,
    "fat_calorie_ratio_max": 0.35,
    "carbs_calorie_ratio_min": 0.35,
    "carbs_calorie_ratio_max": 0.55,
    "fiber_target_g": 21.0,
    "salt_limit_g": 7.5,
    "vegetable_target_servings": 3.0,
    "hydration_target_ml": 2000.0,
}


def _positive(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def calculate_nutrition_targets(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return targets without inferring unavailable sensitive profile attributes.

    Defaults are intentionally broad: 2200 kcal, 1.6 g protein/kg when a
    positive body weight is supplied (otherwise 120 g), 25-35% fat, 35-55%
    carbohydrates, 21 g fiber, <=7.5 g salt, three vegetable servings, and
    2000 ml hydration only when hydration has actually been recorded.
    """
    profile_copy = deepcopy(profile or {})
    custom = profile_copy.get("nutrition_targets")
    custom = custom if isinstance(custom, dict) else {}
    body_weight = _positive(profile_copy.get("body_weight") or profile_copy.get("体重"))
    calorie_target = _positive(custom.get("calorie_target")) or DEFAULTS["calorie_target"]
    protein_target = _positive(custom.get("protein_target_g")) or (
        body_weight * DEFAULTS["protein_g_per_kg"] if body_weight else DEFAULTS["protein_default_g"]
    )
    fat_min = _positive(custom.get("fat_target_min_g")) or calorie_target * DEFAULTS["fat_calorie_ratio_min"] / 9
    fat_max = _positive(custom.get("fat_target_max_g")) or calorie_target * DEFAULTS["fat_calorie_ratio_max"] / 9
    carbs_min = _positive(custom.get("carbs_target_min_g")) or calorie_target * DEFAULTS["carbs_calorie_ratio_min"] / 4
    carbs_max = _positive(custom.get("carbs_target_max_g")) or calorie_target * DEFAULTS["carbs_calorie_ratio_max"] / 4
    return {
        "version": NUTRITION_TARGET_VERSION,
        "calorie_target": round(calorie_target),
        "protein_target_g": round(protein_target, 1),
        "fat_target_min_g": round(fat_min, 1),
        "fat_target_max_g": round(fat_max, 1),
        "carbs_target_min_g": round(carbs_min, 1),
        "carbs_target_max_g": round(carbs_max, 1),
        "fiber_target_g": _positive(custom.get("fiber_target_g")) or DEFAULTS["fiber_target_g"],
        "salt_limit_g": _positive(custom.get("salt_limit_g")) or DEFAULTS["salt_limit_g"],
        "vegetable_target_servings": _positive(custom.get("vegetable_target_servings")) or DEFAULTS["vegetable_target_servings"],
        "hydration_target_ml": _positive(custom.get("hydration_target_ml")) or DEFAULTS["hydration_target_ml"],
        "defaults_used": {
            "calorie_target": "calorie_target" not in custom,
            "protein_target_g": "protein_target_g" not in custom,
            "body_weight_available": body_weight is not None,
        },
    }
