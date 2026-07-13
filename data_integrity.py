from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd


ZERO_MEAL_TEXTS = {
    "",
    "なし",
    "無し",
    "食べていない",
    "食べてない",
    "未食",
    "抜き",
    "スキップ",
    "なしでした",
    "食事なし",
    "朝食なし",
    "昼食なし",
    "夕食なし",
    "晩御飯なし",
    "晩ご飯なし",
}

ZERO_MEAL_FIELDS = {
    "breakfast",
    "lunch",
    "dinner",
    "snack",
    "snacks",
    "朝",
    "昼",
    "夜",
    "間食",
}

def normalize_integrity_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return re.sub(r"\s+", "", text)


NORMALIZED_ZERO_MEAL_TEXTS = {normalize_integrity_text(text) for text in ZERO_MEAL_TEXTS}
NORMALIZED_ZERO_MEAL_FIELDS = {normalize_integrity_text(field) for field in ZERO_MEAL_FIELDS}


def parse_optional_positive_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return None

    text = unicodedata.normalize("NFKC", str(value)).replace(",", "").strip()
    if not text:
        return None

    try:
        number = float(text)
    except ValueError:
        match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(?:kg|キロ)?", text.lower())
        if not match:
            return None
        number = float(match.group(1))

    return number if number > 0 else None


def is_missing_numeric(value: Any) -> bool:
    return parse_optional_positive_number(value) is None


def valid_weight_series(series: pd.Series) -> pd.Series:
    return series.apply(parse_optional_positive_number).astype("float64")


def is_zero_meal_text(value: Any) -> bool:
    return normalize_integrity_text(value) in NORMALIZED_ZERO_MEAL_TEXTS


def is_zero_meal_field(field: str) -> bool:
    return normalize_integrity_text(field) in NORMALIZED_ZERO_MEAL_FIELDS


def format_weight_kg(value: Any) -> str:
    number = parse_optional_positive_number(value)
    return "—" if number is None else f"{number:.1f}kg"


def format_optional_number(value: Any, suffix: str = "", decimals: int = 1) -> str:
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = value is None
    if missing:
        return "—"
    return f"{float(value):.{decimals}f}{suffix}"
