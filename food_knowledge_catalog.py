from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from food_aliases import normalize_food_name
from food_source_models import internal_nutrition_source


GENERIC_CATALOG_VERSION = "1.0"
DICTIONARY_FILES = (
    "food_dictionary.json",
    "brand_dictionary.json",
    "restaurant_dictionary.json",
)
LEGACY_CALORIE_KEYWORDS = {
    "赤飯おにぎり": 230,
    "おにぎり": 190,
    "鮭おにぎり": 190,
    "ツナマヨ": 230,
    "ご飯特盛": 500,
    "ご飯大盛": 380,
    "ご飯": 260,
    "白米": 260,
    "牛丼": 750,
    "牛丼大盛": 950,
    "定食": 900,
    "ハンバーグ定食": 1100,
    "ウマトマ": 900,
    "ハンバーグ": 520,
    "味噌汁": 180,
    "きつねうどん大": 700,
    "きつねうどん": 560,
    "肉ぶっかけうどん": 650,
    "ぶっかけうどん": 500,
    "うどん大": 650,
    "うどん": 450,
    "とり天": 180,
    "天ぷら盛り合わせ": 600,
    "天ぷら": 250,
    "そば": 420,
    "とろろそば": 480,
    "パスタ": 750,
    "ラーメン": 850,
    "カレー": 850,
    "唐揚げ": 350,
    "チキン": 200,
    "グリルチキン": 180,
    "サラダチキン": 120,
    "ゆでたまご": 80,
    "卵": 80,
    "プロテイン": 130,
    "オイコス": 100,
    "ヨーグルト": 100,
    "サラダ": 100,
    "菓子": 220,
    "チョコ": 250,
    "アイス": 260,
    "ジュース": 130,
    "トマトジュース": 70,
    "コーヒー": 20,
    "カフェラテ": 150,
    "ビール": 200,
}


def _key(value: Any) -> str:
    return normalize_food_name(value).lower().replace(" ", "")


def _catalog_item(name: str, kcal: Any, aliases: list[Any], *, catalog: str) -> dict[str, Any] | None:
    try:
        calories = int(kcal)
    except (TypeError, ValueError):
        return None
    if not name or calories < 0:
        return None
    clean_aliases = sorted({str(alias).strip() for alias in [name, *aliases] if str(alias).strip()})
    return {
        "food_id": f"generic:{_key(name)}",
        "brand": None,
        "canonical_name": name,
        "variant": None,
        "size": None,
        "aliases": clean_aliases,
        "category": "generic_food",
        "nutrition": {
            "basis": "per_item",
            "calories_kcal": calories,
            "protein_g": None,
            "fat_g": None,
            "carbs_g": None,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        },
        "source": internal_nutrition_source(
            "legacy_dictionary",
            f"legacy-dictionary:{catalog}:{_key(name)}",
            notes="Existing BodyOS generic dictionary estimate.",
        ),
    }


def load_generic_food_catalog(base_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load legacy JSON dictionaries into one validated generic-catalog contract."""
    root = base_dir or Path(__file__).resolve().parent
    foods: list[dict[str, Any]] = []
    known_names: set[str] = set()
    for filename in DICTIONARY_FILES:
        path = root / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = payload.get("foods", payload) if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            aliases = entry.get("aliases") or []
            aliases = [aliases] if isinstance(aliases, str) else aliases
            item = _catalog_item(str(entry.get("name") or ""), entry.get("kcal"), aliases, catalog=filename)
            if item is not None:
                foods.append(item)
                known_names.add(_key(item["canonical_name"]))

    for name, kcal in LEGACY_CALORIE_KEYWORDS.items():
        if _key(name) in known_names:
            continue
        item = _catalog_item(name, kcal, [], catalog="legacy")
        if item is not None:
            foods.append(item)
    return foods


GENERIC_FOOD_CATALOG = load_generic_food_catalog()


def match_generic_food(item: dict[str, Any], catalog: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Return the longest deterministic generic alias match without mutating inputs."""
    source_catalog = GENERIC_FOOD_CATALOG if catalog is None else catalog
    input_values = [item.get("canonical_name"), item.get("original_fragment"), item.get("raw_text")]
    input_keys = [_key(value) for value in input_values if _key(value)]
    matches: list[tuple[int, dict[str, Any], str]] = []
    for food in source_catalog:
        if not isinstance(food, dict):
            continue
        for alias in food.get("aliases") or []:
            alias_key = _key(alias)
            if alias_key and any(alias_key in input_key for input_key in input_keys):
                matches.append((len(alias_key), food, str(alias)))
    if not matches:
        return None
    _, food, alias = max(matches, key=lambda match: (match[0], _key(match[1].get("canonical_name"))))
    result = deepcopy(food)
    result["matched_alias"] = alias
    return result


__all__ = [
    "GENERIC_CATALOG_VERSION",
    "GENERIC_FOOD_CATALOG",
    "load_generic_food_catalog",
    "match_generic_food",
]
