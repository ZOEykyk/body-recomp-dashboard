from __future__ import annotations

from typing import Any

import unicodedata


FOOD_ALIAS_CATALOG: list[dict[str, Any]] = [
    {
        "canonical_name": "ファミチキ",
        "aliases": ["ファミチキ", "ファミマチキン"],
        "brand": "FamilyMart",
        "brand_aliases": ["ファミマ", "familymart", "family mart"],
        "variants": ["レッド"],
        "default_quantity_allowed": True,
    },
    {
        "canonical_name": "からあげクン",
        "aliases": ["からあげクン", "からあげくん"],
        "brand": "Lawson",
        "brand_aliases": ["ローソン", "lawson"],
        "variants": ["レッド"],
        "default_quantity_allowed": True,
    },
    {
        "canonical_name": "オイコス PRO",
        "aliases": ["オイコスPRO", "オイコス pro", "oikos pro", "オイコス"],
        "brand": None,
        "brand_aliases": [],
        "variants": ["バニラ", "バニラ味"],
        "default_quantity_allowed": True,
    },
    {
        "canonical_name": "SAVAS BIO PRO",
        "aliases": ["SAVAS BIO PRO", "ザバス BIO PRO", "savas bio pro"],
        "brand": "SAVAS",
        "brand_aliases": ["savas", "ザバス"],
        "variants": [],
        "default_quantity_allowed": True,
    },
    {
        "canonical_name": "牛めし 並",
        "aliases": ["牛めし並", "牛めし 並"],
        "brand": "Matsuya",
        "brand_aliases": ["松屋", "matsuya"],
        "variants": ["並"],
        "default_quantity_allowed": True,
    },
    {
        "canonical_name": "午後の紅茶",
        "aliases": ["午後の紅茶"],
        "brand": "Kirin",
        "brand_aliases": ["キリン", "kirin"],
        "variants": [],
        "default_quantity_allowed": True,
    },
    {
        "canonical_name": "理想のトマト",
        "aliases": ["理想のトマト", "伊藤園 理想のトマト"],
        "brand": "Ito En",
        "brand_aliases": ["伊藤園", "ito en"],
        "variants": [],
        "default_quantity_allowed": True,
    },
]

AMBIGUOUS_MEAL_KEYWORDS = ["bbq", "飲み会", "少量", "盛り合わせ", "軽く", "いろいろ"]


def normalize_food_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = " ".join(text.split())
    return text


def alias_key(value: Any) -> str:
    return normalize_food_name(value).lower()


def catalog_entries() -> list[dict[str, Any]]:
    return FOOD_ALIAS_CATALOG


def known_product_phrases() -> list[str]:
    phrases: list[str] = []
    for entry in FOOD_ALIAS_CATALOG:
        phrases.append(str(entry["canonical_name"]))
        phrases.extend(str(alias) for alias in entry.get("aliases", []))
    return sorted(set(phrases), key=len, reverse=True)


def ambiguous_food_text(value: Any) -> bool:
    key = alias_key(value)
    return any(keyword in key for keyword in AMBIGUOUS_MEAL_KEYWORDS)
