from __future__ import annotations

from typing import Any

import unicodedata


FOOD_ALIAS_MAP: dict[str, str] = {
    "オイコスpro": "オイコス PRO",
    "oikos pro": "オイコス PRO",
    "savas bio pro": "SAVAS BIO PRO",
    "ザバス bio pro": "SAVAS BIO PRO",
    "ファミマチキン": "ファミチキ",
    "牛めし並": "牛めし 並",
}


def normalize_food_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = " ".join(text.split())
    return text


def alias_key(value: Any) -> str:
    return normalize_food_name(value).lower()


def resolve_food_alias(value: Any) -> str:
    normalized = normalize_food_name(value)
    key = alias_key(normalized)
    if key in FOOD_ALIAS_MAP:
        return FOOD_ALIAS_MAP[key]

    partial_matches = [
        (len(alias), canonical)
        for alias, canonical in FOOD_ALIAS_MAP.items()
        if alias and alias in key
    ]
    if partial_matches:
        return max(partial_matches, key=lambda item: item[0])[1]
    return normalized
