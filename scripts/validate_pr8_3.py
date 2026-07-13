from __future__ import annotations

from copy import deepcopy
import datetime as dt
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from food_lookup import FOOD_LOOKUP_CATALOG, lookup_food
from food_parser import parse_food_text
from food_source_models import SOURCE_METADATA_FIELDS, explicit_user_label_source, source_metadata_errors
from food_source_policy import is_source_current, is_source_fresh, select_nutrition_source, source_priority
from validate_pr8_2 import install_fake_streamlit


AS_OF = dt.date(2026, 7, 13)


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def source(source_type: str, source_id: str, **overrides: object) -> dict:
    metadata = {
        "source_id": source_id,
        "source_type": source_type,
        "publisher": "BodyOS Test",
        "source_ref": "https://example.test/nutrition",
        "captured_at": "2026-07-01",
        "verified_at": "2026-07-01",
        "valid_from": "2026-01-01",
        "valid_to": None,
        "product_version": "test-v1",
        "reviewer": "BodyOS",
        "verification_status": "verified",
        "confidence": "high",
        "notes": None,
    }
    metadata.update(overrides)
    return metadata


def nutrition(kcal: int) -> dict:
    return {"basis": "per_item", "calories_kcal": kcal}


def candidate(source_metadata: dict, kcal: int) -> dict:
    return {"source": source_metadata, "nutrition": nutrition(kcal)}


def main() -> None:
    expected_priority = [
        "explicit_user_label",
        "official_product_page",
        "official_nutrition_table",
        "official_api_or_catalog",
        "bodyos_verified",
        "user_verified",
        "general_reference",
        "legacy_dictionary",
        "fallback_estimate",
    ]
    assert_equal([source_priority(value) for value in expected_priority], list(range(1, 10)), "source priority")

    explicit_source = explicit_user_label_source(captured_at="2026-07-13")
    assert_equal(set(explicit_source), set(SOURCE_METADATA_FIELDS), "shared explicit source contract")
    assert_equal(source_metadata_errors(explicit_source), [], "explicit source validation")

    official_source = source("official_product_page", "official-1")
    explicit_vs_official = select_nutrition_source(
        [candidate(official_source, 250), candidate(explicit_source, 223)], as_of=AS_OF
    )
    assert_equal(explicit_vs_official["selected"]["source"]["source_type"], "explicit_user_label", "explicit priority")
    assert_equal(explicit_vs_official["status"], "selected_with_conflict", "explicit conflict state")
    assert_equal(explicit_vs_official["needs_review"], True, "explicit conflict review")

    same_priority_conflict = select_nutrition_source(
        [candidate(source("official_product_page", "official-a"), 250), candidate(source("official_product_page", "official-b"), 310)],
        as_of=AS_OF,
    )
    assert_equal(same_priority_conflict["status"], "conflict", "same priority conflict")
    assert_equal(same_priority_conflict["selected"], None, "same priority conflict selection")

    expired_official = source("official_product_page", "official-expired", valid_to="2026-01-01")
    legacy_source = source("legacy_dictionary", "legacy-1", confidence="medium")
    expired_fallback = select_nutrition_source(
        [candidate(expired_official, 250), candidate(legacy_source, 260)], as_of=AS_OF
    )
    assert_equal(expired_fallback["selected"]["source"]["source_type"], "legacy_dictionary", "expired source excluded")
    assert_equal(is_source_current(expired_official, AS_OF), False, "expired source current flag")

    stale_official = source("official_product_page", "official-stale", verified_at="2020-01-01")
    stale_selection = select_nutrition_source([candidate(stale_official, 250)], as_of=AS_OF)
    assert_equal(is_source_fresh(stale_official, AS_OF), False, "stale source freshness")
    assert_equal(stale_selection["needs_review"], True, "stale source review")

    rejected = source("official_product_page", "official-rejected", verification_status="rejected")
    assert_equal(select_nutrition_source([candidate(rejected, 250)], as_of=AS_OF)["status"], "not_found", "rejected excluded")

    catalog_item = deepcopy(FOOD_LOOKUP_CATALOG[0])
    original_catalog_item = deepcopy(catalog_item)
    lookup = lookup_food(
        {"brand": "FamilyMart", "canonical_name": "ファミチキ", "variant": None, "size": None},
        catalog=[catalog_item],
        as_of=AS_OF,
    )
    assert_equal(catalog_item, original_catalog_item, "lookup catalog input mutation")
    assert_equal(lookup["source_selection"]["status"], "selected", "lookup source selection")
    assert_equal(lookup["source_selection"]["selected"]["source"]["source_type"], "official_product_page", "lookup official source")

    install_fake_streamlit()
    import app

    explicit_detail = app.estimate_calorie_detail("ファミチキ2個、1個あたり223kcal", "間食")
    assert_equal(
        explicit_detail["nutrition_source_decisions"][0]["selected"]["source"]["source_type"],
        "explicit_user_label",
        "app explicit source selection",
    )
    lookup_detail = app.estimate_calorie_detail("ファミチキ2個", "間食")
    assert_equal(
        lookup_detail["nutrition_source_decisions"][0]["selected"]["source"]["source_type"],
        "official_product_page",
        "app lookup source selection",
    )
    fallback_detail = app.estimate_calorie_detail("見慣れない軽食", "間食")
    assert_equal(
        fallback_detail["nutrition_source_decisions"][0]["selected"]["source"]["source_type"],
        "fallback_estimate",
        "app fallback source selection",
    )

    if subprocess.run(["git", "diff", "--quiet", "--", "records.csv"], cwd=ROOT, check=False).returncode:
        raise AssertionError("records.csv must remain unchanged")
    if "food_source" in (ROOT / "records.csv").read_text(encoding="utf-8-sig").splitlines()[0]:
        raise AssertionError("CSV schema must not include food source fields")

    print("PR8.3 food source policy validation passed")


if __name__ == "__main__":
    main()
