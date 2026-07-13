from __future__ import annotations

import re
import unicodedata
from typing import Any

from data_integrity import is_zero_meal_field, is_zero_meal_text
from food_aliases import (
    ambiguous_food_text,
    catalog_entries,
    known_product_phrases,
    normalize_food_name,
)

FOOD_PARSER_VERSION = "1.0"
QUANTITY_UNITS = "個|本|杯|枚|缶|パック|袋|人前|食|皿|切れ|粒|膳"
SIZE_UNITS = "g|gram|grams|グラム|ml|mL|ML|ミリリットル"
TEXT_DELIMITER_PATTERN = r"[\n\r,，、;；/／|＋+]+"
INNER_DELIMITER_PATTERN = r"[・･]+"
PROTECTED_SPLIT_PHRASES = known_product_phrases()


def normalized_text(value: Any) -> str:
    return normalize_food_name(value)


def extract_explicit_nutrition(text: str) -> dict[str, Any]:
    normalized = normalized_text(text)
    lowered = normalized.lower()

    calories = [round(float(value)) for value in re.findall(r"(\d+(?:\.\d+)?)\s*(?:kcal|キロカロリー)", lowered)]
    protein = [float(value) for value in re.findall(r"(?:p|protein|たんぱく質|タンパク質)\s*(\d+(?:\.\d+)?)\s*g", lowered)]
    fat = [float(value) for value in re.findall(r"(?:f|fat|脂質)\s*(\d+(?:\.\d+)?)\s*g", lowered)]
    carbs = [float(value) for value in re.findall(r"(?:c|carb|carbs|炭水化物|糖質)\s*(\d+(?:\.\d+)?)\s*g", lowered)]

    basis = explicit_nutrition_basis(lowered)
    return {
        "calories_kcal": sum(calories) if calories else None,
        "protein_g": sum(protein) if protein else None,
        "fat_g": sum(fat) if fat else None,
        "carbs_g": sum(carbs) if carbs else None,
        "basis": basis,
        "value_origin": "explicit_text" if calories or protein or fat or carbs else None,
        "entries": {
            "calories_kcal": calories,
            "protein_g": protein,
            "fat_g": fat,
            "carbs_g": carbs,
        },
    }


def explicit_nutrition_basis(lowered_text: str) -> str:
    if re.search(r"100\s*g\s*あたり|100gあたり", lowered_text):
        return "per_100g"
    if re.search(r"100\s*ml\s*あたり|100mlあたり", lowered_text):
        return "per_100ml"
    if re.search(r"(?:1個|一個|1本|一本|1パック|一パック|1杯|一杯)\s*あたり|あたり", lowered_text):
        return "per_item"
    if re.search(r"(?:1袋|一袋|1パック|一パック|1包装|一包装|1本|一本)\s*(?:あたり)?", lowered_text):
        return "per_package"
    if re.search(r"合計|全部|total", lowered_text):
        return "total"
    return "unknown"


def strip_explicit_nutrition(text: str) -> str:
    stripped = re.sub(r"(?:1個|一個|1本|一本|1パック|一パック|100\s*g|100\s*ml)?\s*あたり", " ", text, flags=re.IGNORECASE)
    stripped = re.sub(r"\d+(?:\.\d+)?\s*(?:kcal|キロカロリー)", " ", stripped, flags=re.IGNORECASE)
    stripped = re.sub(
        r"(?:p|protein|たんぱく質|タンパク質|f|fat|脂質|c|carb|carbs|炭水化物|糖質)\s*\d+(?:\.\d+)?\s*g",
        " ",
        stripped,
        flags=re.IGNORECASE,
    )
    return stripped


def protect_split_phrases(text: str) -> tuple[str, dict[str, str]]:
    protected = text
    placeholders: dict[str, str] = {}
    for index, phrase in enumerate(PROTECTED_SPLIT_PHRASES):
        if not phrase or phrase not in protected:
            continue
        placeholder = f"__FOODPHRASE{index}__"
        protected = protected.replace(phrase, placeholder)
        placeholders[placeholder] = phrase
    return protected, placeholders


def restore_split_phrases(text: str, placeholders: dict[str, str]) -> str:
    restored = text
    for placeholder, phrase in placeholders.items():
        restored = restored.replace(placeholder, phrase)
    return restored


def split_food_segments(text: str) -> list[str]:
    working = unicodedata.normalize("NFKC", str(text or ""))
    working = strip_explicit_nutrition(working)
    working = re.sub(r"[()（）\[\]【】]", "、", working)
    working, placeholders = protect_split_phrases(working)
    working = re.sub(r"\s*(?:に加えて|あと|と|&)\s*", "、", working)
    coarse_segments = re.split(TEXT_DELIMITER_PATTERN, working)

    segments: list[str] = []
    for segment in coarse_segments:
        segment = restore_split_phrases(segment, placeholders).strip(" \t-:：。")
        if not segment:
            continue
        for inner in re.split(INNER_DELIMITER_PATTERN, segment):
            inner = restore_split_phrases(inner, placeholders).strip(" \t-:：。")
            if inner:
                segments.append(inner)
    return segments


def parse_amount(value: str) -> int | float:
    amount = float(value)
    return int(amount) if amount.is_integer() else amount


def extract_size(segment: str) -> dict[str, Any] | None:
    size_match = re.search(rf"(?:内容量\s*)?(\d+(?:\.\d+)?)\s*({SIZE_UNITS})", segment, flags=re.IGNORECASE)
    if not size_match:
        return None
    unit = size_match.group(2)
    normalized_unit = "ml" if unit.lower() == "ml" or unit == "ミリリットル" else "g"
    amount = parse_amount(size_match.group(1))
    return {
        "amount": amount,
        "unit": normalized_unit,
        "raw": size_match.group(0),
        "text": f"{amount:g}{normalized_unit}" if isinstance(amount, float) else f"{amount}{normalized_unit}",
    }


def extract_quantity(segment: str, size: dict[str, Any] | None = None) -> dict[str, Any]:
    quantity_match = re.search(rf"(\d+(?:\.\d+)?)\s*({QUANTITY_UNITS})", segment)
    if not quantity_match and size is not None and not str(size["raw"]).startswith("内容量"):
        return {"amount": size["amount"], "unit": size["unit"], "raw": size["raw"]}
    if not quantity_match:
        return {"amount": None, "unit": None, "raw": None}

    return {
        "amount": parse_amount(quantity_match.group(1)),
        "unit": quantity_match.group(2),
        "raw": quantity_match.group(0),
    }


def clean_item_name(segment: str) -> str:
    cleaned = re.sub(rf"(\d+(?:\.\d+)?)\s*({QUANTITY_UNITS})", " ", segment)
    cleaned = re.sub(rf"(?:内容量\s*)?\d+(?:\.\d+)?\s*({SIZE_UNITS})", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t-:：。")
    return cleaned or segment.strip()


def detect_alias(display_name: str) -> dict[str, Any]:
    key = normalized_text(display_name).lower()
    best: tuple[int, str, dict[str, Any], str] | None = None
    for entry in catalog_entries():
        aliases = [entry["canonical_name"], *entry.get("aliases", [])]
        for alias in aliases:
            alias_key = normalized_text(alias).lower()
            compact_key = key.replace(" ", "")
            compact_alias = alias_key.replace(" ", "")
            if not alias_key:
                continue
            if key == alias_key:
                return {"entry": entry, "matched_alias": alias, "resolution": "alias_exact"}
            if compact_key == compact_alias:
                return {"entry": entry, "matched_alias": alias, "resolution": "normalized_exact"}
            if alias_key in key:
                candidate = (len(alias_key), alias, entry, "alias_exact")
                if best is None or candidate[0] > best[0]:
                    best = candidate

        for brand_alias in entry.get("brand_aliases", []):
            brand_key = normalized_text(brand_alias).lower()
            if brand_key and brand_key in key:
                for alias in aliases:
                    alias_key = normalized_text(alias).lower()
                    if alias_key and alias_key in key:
                        return {"entry": entry, "matched_alias": alias, "resolution": "brand_context"}

    if best is None:
        return {"entry": None, "matched_alias": None, "resolution": "unresolved"}
    return {"entry": best[2], "matched_alias": best[1], "resolution": best[3]}


def detect_brand(display_name: str, entry: dict[str, Any] | None) -> str | None:
    if entry is None:
        return None
    key = normalized_text(display_name).lower()
    for brand_alias in entry.get("brand_aliases", []):
        if normalized_text(brand_alias).lower() in key:
            return entry.get("brand")
    return entry.get("brand")


def detect_variant(display_name: str, entry: dict[str, Any] | None) -> str | None:
    if entry is None:
        return None
    key = normalized_text(display_name).lower()
    for variant in entry.get("variants", []):
        variant_text = str(variant)
        normalized_variant = normalized_text(variant_text).lower()
        if normalized_variant and normalized_variant in key:
            return variant_text.replace("味", "")
    return None


def default_quantity_allowed(entry: dict[str, Any] | None, display_name: str) -> bool:
    if entry is None:
        return False
    if ambiguous_food_text(display_name):
        return False
    return bool(entry.get("default_quantity_allowed", False))


def explicit_nutrition_for_fragment(fragment: str, parser_nutrition: dict[str, Any]) -> dict[str, Any]:
    fragment_nutrition = extract_explicit_nutrition(fragment)
    return fragment_nutrition if nutrition_present(fragment_nutrition) else parser_nutrition


def parse_food_item(segment: str, index: int) -> dict[str, Any]:
    size = extract_size(segment)
    quantity = extract_quantity(segment, size)
    display_name = clean_item_name(segment)
    alias_result = detect_alias(display_name)
    entry = alias_result["entry"]
    resolution = alias_result["resolution"]
    canonical_name = entry["canonical_name"] if entry else display_name

    if quantity["amount"] is None and default_quantity_allowed(entry, display_name):
        quantity = {"amount": 1, "unit": None, "raw": None}

    unresolved = resolution == "unresolved"
    needs_review = unresolved or quantity["amount"] is None or ambiguous_food_text(display_name)
    confidence = "low" if needs_review else "high" if resolution in {"alias_exact", "brand_context", "normalized_exact"} else "medium"

    return {
        "index": index,
        "raw_text": segment,
        "original_fragment": segment,
        "name": display_name,
        "brand": detect_brand(display_name, entry),
        "canonical_name": canonical_name,
        "variant": detect_variant(display_name, entry),
        "size": size["text"] if size else None,
        "quantity": quantity["amount"],
        "unit": quantity["unit"],
        "resolution": resolution,
        "needs_review": needs_review,
        "explicit_nutrition": None,
        "normalized_name": normalized_text(canonical_name).lower(),
        "quantity_detail": quantity,
        "size_detail": size,
        "nutrition": None,
        "confidence": confidence,
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
    for item in items:
        item["explicit_nutrition"] = explicit_nutrition_for_fragment(item["original_fragment"], explicit_nutrition)

    if zero_meal:
        confidence = "high"
    elif any(item["needs_review"] for item in items):
        confidence = "low"
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
