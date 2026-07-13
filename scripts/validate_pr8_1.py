from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from food_parser import parse_food_text


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def main() -> None:
    famichiki = parse_food_text("ファミチキ2個", "昼")
    assert_equal(famichiki["item_count"], 1, "famichiki item_count")
    assert_equal(famichiki["items"][0]["name"], "ファミチキ", "famichiki name")
    assert_equal(famichiki["items"][0]["quantity"]["amount"], 2, "famichiki quantity")

    composite = parse_food_text("旨だしとりそぼろ丼＋チョレギサラダ＋豚汁", "昼")
    assert_equal(composite["item_count"], 3, "composite item_count")
    assert_equal([item["name"] for item in composite["items"]], ["旨だしとりそぼろ丼", "チョレギサラダ", "豚汁"], "composite names")

    explicit = parse_food_text("223kcal、P12g、F15g、C14g", "間食")
    assert_equal(explicit["explicit_nutrition"]["calories_kcal"], 223, "explicit kcal")
    assert_equal(explicit["explicit_nutrition"]["protein_g"], 12.0, "explicit protein")
    assert_equal(explicit["explicit_nutrition"]["fat_g"], 15.0, "explicit fat")
    assert_equal(explicit["explicit_nutrition"]["carbs_g"], 14.0, "explicit carbs")
    assert_equal(explicit["item_count"], 0, "explicit item_count")

    alias = parse_food_text("オイコスPROバニラ味", "朝")
    assert_equal(alias["items"][0]["name"], "オイコスPROバニラ味", "alias raw name")
    assert_equal(alias["items"][0]["canonical_name"], "オイコス PRO", "alias canonical name")

    zero_meal = parse_food_text("なし", "夜")
    assert_equal(zero_meal["is_zero_meal"], True, "zero meal")
    assert_equal(zero_meal["item_count"], 0, "zero meal item_count")

    original = "SAVAS BIO PRO"
    before = deepcopy(original)
    parsed = parse_food_text(original, "間食")
    assert_equal(original, before, "pure function input unchanged")
    assert_equal(parsed["items"][0]["canonical_name"], "SAVAS BIO PRO", "savas canonical name")

    required_keys = {
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
    assert_equal(set(parsed.keys()), required_keys, "result keys")
    print("PR8.1 food parser validation passed")


if __name__ == "__main__":
    main()
