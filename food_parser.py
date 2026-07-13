from __future__ import annotations

import re
import unicodedata
from typing import Any

from data_integrity import is_zero_meal_field, is_zero_meal_text
from food_aliases import normalize_food_name, resolve_food_alias

FOOD_PARSER_VERSION = "1.0"
QUANTITY_UNITS = "個|本|杯|枚|缶|パック|袋|人前|食|皿|切れ|粒"
TEXT_DELIMITER_PATTERN = r"[\n\r,，、;；/／|＋+]+"
INNER_DELIMITER_PATTERN = r"[・･]+"


def normalized_text(value: Any) -> str:
    return normalize_food_name(value)


def extract_explicit_nutrition(text: str) -> dict[str, Any]:
    normalized = normalized_text(text)
    lowered = normalized.lower()

    calories = [round(float(value)) for value in re.findall(r"(\d+(?:\.\d+)?)\s*(?:kcal|キロカロリー)", lowered)]
    protein = [float(value) for value in re.findall(r"(?:p|protein|たんぱく質|タンパク質)\s*(\d+(?:\.\d+)?)\s*g", lowered)]
    fat = [float(value) for value in re.findall(r"(?:f|fat|脂質)\s*(\d+(?:\.\d+)?)\s*g", lowered)]
    carbs = [float(value) for value in re.findall(r"(?:c|carb|carbs|炭水化物|糖質)\s*(\d+(?:\.\d+)?)\s*g", lowered)]

    return {
        "calories_kcal": sum(calories) if calories else None,
        "protein_g": sum(protein) if protein else None,
        "fat_g": sum(fat) if fat else None,
        "carbs_g": sum(carbs) if carbs else None,
        "entries": {
            "calories_kcal": calories,
            "protein_g": protein,
            "fat_g": fat,
            "carbs_g": carbs,
        },
    }


def strip_explicit_nutrition(text: str) -> str:
    stripped = re.sub(r"\d+(?:\.\d+)?\s*(?:kcal|キロカロリー)", " ", text, flags=re.IGNORECASE)
    stripped = re.sub(
        r"(?:p|protein|たんぱく質|タンパク質|f|fat|脂質|c|carb|carbs|炭水化物|糖質)\s*\d+(?:\.\d+)?\s*g",
        " ",
        stripped,
        flags=re.IGNORECASE,
    )
    return stripped


def split_food_segments(text: str) -> list[str]:
    working = unicodedata.normalize("NFKC", str(text or ""))
    working = strip_explicit_nutrition(working)
    working = re.sub(r"[()（）\[\]【】]", "、", working)
    coarse_segments = re.split(TEXT_DELIMITER_PATTERN, working)

    segments: list[str] = []
    for segment in coarse_segments:
        segment = segment.strip(" \t-:：。")
        if not segment:
            continue
        for inner in re.split(INNER_DELIMITER_PATTERN, segment):
            inner = inner.strip(" \t-:：。")
            if inner:
                segments.append(inner)
    return segments


def extract_quantity(segment: str) -> dict[str, Any]:
    quantity_match = re.search(rf"(\d+(?:\.\d+)?)\s*({QUANTITY_UNITS})", segment)
    if not quantity_match:
        return {"amount": 1, "unit": None, "raw": None}

    amount = float(quantity_match.group(1))
    if amount.is_integer():
        amount = int(amount)
    return {
        "amount": amount,
        "unit": quantity_match.group(2),
        "raw": quantity_match.group(0),
    }


def clean_item_name(segment: str) -> str:
    cleaned = re.sub(rf"(\d+(?:\.\d+)?)\s*({QUANTITY_UNITS})", " ", segment)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t-:：。")
    return cleaned or segment.strip()


def parse_food_item(segment: str, index: int) -> dict[str, Any]:
    quantity = extract_quantity(segment)
    display_name = clean_item_name(segment)
    canonical_name = resolve_food_alias(display_name)
    return {
        "index": index,
        "raw_text": segment,
        "name": display_name,
        "canonical_name": canonical_name,
        "normalized_name": normalized_text(canonical_name).lower(),
        "quantity": quantity,
        "nutrition": None,
        "confidence": "medium" if canonical_name else "low",
    }


def nutrition_present(nutrition: dict[str, Any]) -> bool:
    return any(
        nutrition.get(key) is not None
        for key in ["calories_kcal", "protein_g", "fat_g", "carbs_g"]
    )


def parse_food_text(text: str, meal_type: str | None = None) -> dict[str, Any]:
    """Parse meal text into deterministic structure without looking up nutrition values."""
    raw_text = "" if text is None else str(text)
    normalized = normalized_text(raw_text)
    zero_meal = bool(is_zero_meal_field(meal_type or "") and is_zero_meal_text(raw_text))
    explicit_nutrition = extract_explicit_nutrition(raw_text)
    segments = [] if zero_meal else split_food_segments(raw_text)
    items = [parse_food_item(segment, index) for index, segment in enumerate(segments)]

    if zero_meal:
        confidence = "high"
    elif nutrition_present(explicit_nutrition) or items:
        confidence = "medium"
    elif normalized:
        confidence = "low"
    else:
        confidence = "low"

    return {
        "metadata": {"food_parser_version": FOOD_PARSER_VERSION},
        "raw_text": raw_text,
        "normalized_text": normalized,
        "meal_type": meal_type,
        "is_zero_meal": zero_meal,
        "explicit_nutrition": explicit_nutrition,
        "items": items,
        "item_count": len(items),
        "confidence": confidence,
    }
