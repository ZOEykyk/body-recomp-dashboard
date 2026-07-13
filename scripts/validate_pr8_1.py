from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from food_parser import parse_food_text


REQUIRED_ITEM_KEYS = {
    "brand",
    "canonical_name",
    "variant",
    "size",
    "quantity",
    "unit",
    "original_fragment",
    "resolution",
    "confidence",
    "needs_review",
    "explicit_nutrition",
}


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value: bool, label: str) -> None:
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def first_item(text: str, meal_type: str = "昼") -> dict:
    parsed = parse_food_text(text, meal_type)
    assert_true(parsed["items"], f"{text} has items")
    item = parsed["items"][0]
    missing = REQUIRED_ITEM_KEYS - set(item)
    if missing:
        raise AssertionError(f"{text} item missing keys: {sorted(missing)}")
    return item


def main() -> None:
    known_alias = first_item("ファミチキ2個")
    assert_equal(known_alias["canonical_name"], "ファミチキ", "known alias canonical")
    assert_equal(known_alias["quantity"], 2, "known alias quantity")
    assert_equal(known_alias["unit"], "個", "known alias unit")
    assert_equal(known_alias["resolution"], "alias_exact", "known alias resolution")
    assert_equal(known_alias["needs_review"], False, "known alias review")

    normalized_exact = first_item("SAVASBIOPRO")
    assert_equal(normalized_exact["canonical_name"], "SAVAS BIO PRO", "normalized exact canonical")
    assert_equal(normalized_exact["resolution"], "normalized_exact", "normalized exact resolution")

    brand = first_item("ファミマ ファミチキ")
    assert_equal(brand["brand"], "FamilyMart", "brand context brand")
    assert_equal(brand["canonical_name"], "ファミチキ", "brand context canonical")
    assert_equal(brand["resolution"], "brand_context", "brand context resolution")

    variant = first_item("ファミチキ レッド")
    assert_equal(variant["canonical_name"], "ファミチキ", "variant canonical")
    assert_equal(variant["variant"], "レッド", "variant")

    oikos = first_item("オイコスPRO バニラ味", "朝")
    assert_equal(oikos["canonical_name"], "オイコス PRO", "oikos canonical")
    assert_equal(oikos["variant"], "バニラ", "oikos variant")

    savas = first_item("SAVAS BIO PRO 250ml", "間食")
    assert_equal(savas["canonical_name"], "SAVAS BIO PRO", "savas canonical")
    assert_equal(savas["size"], "250ml", "savas size")
    assert_equal(savas["quantity"], 250, "savas quantity")
    assert_equal(savas["unit"], "ml", "savas unit")

    quantity_cases = [
        ("ファミチキ2個", 2, "個"),
        ("SAVAS BIO PRO 3本", 3, "本"),
        ("午後の紅茶1杯", 1, "杯"),
        ("オイコスPRO 1パック", 1, "パック"),
        ("刺身3切れ", 3, "切れ"),
        ("鶏むね肉95g", 95, "g"),
        ("ごはん180g", 180, "g"),
        ("SAVAS BIO PRO 250mL", 250, "ml"),
        ("ごはん0.7膳", 0.7, "膳"),
    ]
    for text, amount, unit in quantity_cases:
        item = first_item(text)
        assert_equal(item["quantity"], amount, f"{text} quantity")
        assert_equal(item["unit"], unit, f"{text} unit")

    split = parse_food_text("ファミチキとオイコスPRO あと SAVAS BIO PROに加えて午後の紅茶", "昼")
    assert_equal([item["canonical_name"] for item in split["items"]], ["ファミチキ", "オイコス PRO", "SAVAS BIO PRO", "午後の紅茶"], "Japanese conjunction splitting")

    protected = parse_food_text("午後の紅茶＋理想のトマト＋からあげクン レッド", "昼")
    assert_equal([item["canonical_name"] for item in protected["items"]], ["午後の紅茶", "理想のトマト", "からあげクン"], "protected product splitting")
    assert_equal(protected["items"][2]["variant"], "レッド", "protected variant")

    ambiguous = first_item("飲み会で少量")
    assert_equal(ambiguous["resolution"], "unresolved", "ambiguous resolution")
    assert_equal(ambiguous["needs_review"], True, "ambiguous review")
    assert_equal(ambiguous["confidence"], "low", "ambiguous confidence")

    unresolved = first_item("おばあちゃん特製カレー")
    assert_equal(unresolved["resolution"], "unresolved", "unresolved resolution")
    assert_equal(unresolved["original_fragment"], "おばあちゃん特製カレー", "unresolved original")
    assert_equal(unresolved["needs_review"], True, "unresolved review")

    per_item = first_item("ファミチキ2個、1個あたり223kcal")
    assert_equal(per_item["quantity"], 2, "per_item quantity")
    assert_equal(per_item["explicit_nutrition"]["calories_kcal"], 223, "per_item kcal")
    assert_equal(per_item["explicit_nutrition"]["basis"], "per_item", "per_item basis")
    assert_equal(per_item["explicit_nutrition"]["value_origin"], "explicit_text", "per_item origin")

    per_100g = parse_food_text("100gあたり250kcal、内容量180g", "昼")
    assert_equal(per_100g["explicit_nutrition"]["calories_kcal"], 250, "per_100g kcal")
    assert_equal(per_100g["explicit_nutrition"]["basis"], "per_100g", "per_100g basis")
    assert_equal(per_100g["items"][0]["size"], "180g", "per_100g size")

    zero_meal = parse_food_text("なし", "夜")
    assert_equal(zero_meal["is_zero_meal"], True, "zero meal")
    assert_equal(zero_meal["item_count"], 0, "zero meal item_count")

    original = "SAVAS BIO PRO"
    before = deepcopy(original)
    parsed = parse_food_text(original, "間食")
    assert_equal(original, before, "pure function input unchanged")
    assert_equal(parsed["items"][0]["canonical_name"], "SAVAS BIO PRO", "savas canonical name")

    required_result_keys = {
        "metadata",
        "raw_text",
        "normalized_text",
        "meal_type",
        "is_zero_meal",
        "explicit_nutrition",
        "items",
        "item_count",
        "confidence",
    }
    assert_equal(set(parsed.keys()), required_result_keys, "result keys")
    print("PR8.1 food parser validation passed")


if __name__ == "__main__":
    main()
