from __future__ import annotations

from copy import deepcopy
import datetime as dt
from pathlib import Path
import subprocess
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from food_lookup import (
    FOOD_LOOKUP_CATALOG,
    calculate_lookup_total,
    lookup_food,
    lookup_parsed_foods,
    validate_catalog,
)
from food_parser import parse_food_text


class FakeStreamlit(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("streamlit")
        self.secrets = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __getattr__(self, _name):
        return self.noop

    def noop(self, *args, **kwargs):
        return None

    def form(self, *_args, **_kwargs):
        return self

    def expander(self, *_args, **_kwargs):
        return self

    def columns(self, spec, *_args, **_kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(count)]

    def date_input(self, *_args, value=None, **_kwargs):
        return value or dt.date.today()

    def selectbox(self, _label, options, *_args, **_kwargs):
        return list(options)[0]

    def number_input(self, *_args, value=0, **_kwargs):
        return value

    def slider(self, *_args, value=0, **_kwargs):
        return value

    def text_input(self, *_args, **_kwargs):
        return ""

    def text_area(self, *_args, **_kwargs):
        return ""

    def checkbox(self, *_args, **_kwargs):
        return False

    def button(self, *_args, **_kwargs):
        return False

    def form_submit_button(self, *_args, **_kwargs):
        return False


def install_fake_streamlit() -> None:
    fake_streamlit = FakeStreamlit()
    fake_components = types.ModuleType("streamlit.components")
    fake_components_v1 = types.ModuleType("streamlit.components.v1")
    fake_components_v1.html = lambda *_args, **_kwargs: None
    fake_components.v1 = fake_components_v1
    fake_streamlit.components = fake_components
    sys.modules["streamlit"] = fake_streamlit
    sys.modules["streamlit.components"] = fake_components
    sys.modules["streamlit.components.v1"] = fake_components_v1


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def sample_item(brand: str | None = None) -> dict:
    return {
        "brand": brand,
        "canonical_name": "ファミチキ",
        "variant": None,
        "size": None,
        "quantity": 1,
        "unit": "個",
        "original_fragment": "ファミチキ",
        "explicit_nutrition": None,
    }


def nutrition(basis: str, calories: float = 100) -> dict:
    return {
        "basis": basis,
        "calories_kcal": calories,
        "protein_g": 10,
        "fat_g": 5,
        "carbs_g": 12,
        "sugar_g": None,
        "fiber_g": None,
        "salt_g": None,
    }


def main() -> None:
    required_result_keys = {
        "metadata",
        "status",
        "matched",
        "match_type",
        "confidence",
        "needs_review",
        "candidates",
        "original_identity",
        "match",
        "food",
        "nutrition",
        "source",
        "source_selection",
        "input",
    }
    family_result = lookup_food(sample_item("FamilyMart"))
    assert_equal(set(family_result), required_result_keys, "lookup result contract")
    assert_equal(family_result["status"], "matched", "FamilyMart plus famichiki")
    assert_equal(family_result["match_type"], "brand_exact", "brand match type")
    assert_equal(family_result["confidence"], "high", "brand confidence")
    assert_equal(family_result["needs_review"], False, "matched review")

    mismatch = lookup_food(sample_item("McDonald's"))
    assert_equal(mismatch["status"], "not_found", "brand mismatch")
    assert_equal(mismatch["matched"], False, "brand mismatch matched")

    unbranded = lookup_food(sample_item())
    assert_equal(unbranded["status"], "matched", "unbranded unique identity")
    assert_equal(unbranded["match_type"], "canonical_exact", "unbranded match type")

    parser_item = parse_food_text("ファミマ ファミチキ2個", "間食")["items"][0]
    before_item = deepcopy(parser_item)
    parsed_result = lookup_food(parser_item)
    assert_equal(parser_item, before_item, "lookup input mutation")
    assert_equal(parsed_result["status"], "matched", "parser item match")

    breakfast = parse_food_text("ソーセージエッグマフィン、ハッシュポテト", "朝")
    before_parsed = deepcopy(breakfast)
    breakfast_results = lookup_parsed_foods(breakfast)
    assert_equal(breakfast, before_parsed, "parsed foods mutation")
    assert_equal(breakfast_results["matched_count"], 2, "mcdonalds seed matches")

    ambiguous_catalog = [deepcopy(FOOD_LOOKUP_CATALOG[0]), deepcopy(FOOD_LOOKUP_CATALOG[0])]
    ambiguous_catalog[1]["id"] = "familymart-famichiki-alternate"
    ambiguous = lookup_food(sample_item(), catalog=ambiguous_catalog)
    assert_equal(ambiguous["status"], "ambiguous", "ambiguous status")
    assert_equal(ambiguous["needs_review"], True, "ambiguous review")
    assert_equal(len(ambiguous["candidates"]), 2, "ambiguous candidates")
    assert_equal(
        set(ambiguous["candidates"][0]),
        {"food_id", "brand", "canonical_name", "variant", "size", "nutrition", "source_type"},
        "candidate contract",
    )

    per_item = calculate_lookup_total(family_result, 2, "個")
    assert_equal(per_item["calories_kcal"], 503.4, "per_item total")
    per_100g_result = {"matched": True, "nutrition": nutrition("per_100g", 250)}
    per_100g = calculate_lookup_total(per_100g_result, 180, "g")
    assert_equal(per_100g["calories_kcal"], 450.0, "per_100g total")
    incompatible = calculate_lookup_total(family_result, 180, "g")
    assert_equal(incompatible["needs_review"], True, "incompatible unit review")

    explicit_item = sample_item()
    explicit_item["explicit_nutrition"] = {"calories_kcal": 223}
    explicit = lookup_food(explicit_item)
    assert_equal(explicit["status"], "skipped_explicit_nutrition", "explicit nutrition skip")

    inactive = deepcopy(FOOD_LOOKUP_CATALOG[0])
    inactive["is_active"] = False
    assert_equal(lookup_food(sample_item(), catalog=[inactive])["status"], "not_found", "inactive record")
    expired = deepcopy(FOOD_LOOKUP_CATALOG[0])
    expired["valid_to"] = "2020-01-01"
    assert_equal(lookup_food(sample_item(), catalog=[expired])["status"], "not_found", "expired record")

    duplicate_validation = validate_catalog(ambiguous_catalog)
    assert_equal(duplicate_validation["valid_items"], [], "duplicate active identity excluded")
    if not any("duplicate active identity" in warning for warning in duplicate_validation["warnings"]):
        raise AssertionError("duplicate active identity warning missing")

    duplicate_id_catalog = [deepcopy(FOOD_LOOKUP_CATALOG[0]), deepcopy(FOOD_LOOKUP_CATALOG[1])]
    duplicate_id_catalog[1]["id"] = duplicate_id_catalog[0]["id"]
    duplicate_id_validation = validate_catalog(duplicate_id_catalog)
    assert_equal(duplicate_id_validation["valid_items"], [], "duplicate food id excluded")
    if not any("duplicate food_id" in warning for warning in duplicate_id_validation["warnings"]):
        raise AssertionError("duplicate food_id warning missing")

    invalid_basis = deepcopy(FOOD_LOOKUP_CATALOG[0])
    invalid_basis["nutrition"]["basis"] = "per_universe"
    assert_equal(validate_catalog([invalid_basis])["valid_items"], [], "invalid basis excluded")
    negative_nutrition = deepcopy(FOOD_LOOKUP_CATALOG[0])
    negative_nutrition["nutrition"]["protein_g"] = -1
    assert_equal(validate_catalog([negative_nutrition])["valid_items"], [], "negative nutrition excluded")
    missing_verified_date = deepcopy(FOOD_LOOKUP_CATALOG[0])
    missing_verified_date["source"].pop("verified_at")
    assert_equal(validate_catalog([missing_verified_date])["valid_items"], [], "missing verified date excluded")
    invalid_window = deepcopy(FOOD_LOOKUP_CATALOG[0])
    invalid_window["valid_from"] = "2026-12-31"
    invalid_window["valid_to"] = "2026-01-01"
    assert_equal(validate_catalog([invalid_window])["valid_items"], [], "invalid validity window excluded")

    malformed_validation = validate_catalog([{"id": "bad"}])
    assert_equal(malformed_validation["valid_items"], [], "malformed catalog excluded")
    if not malformed_validation["warnings"]:
        raise AssertionError("malformed catalog warning missing")

    install_fake_streamlit()
    import app

    explicit_detail = app.estimate_calorie_detail("ファミチキ2個、1個あたり223kcal", "間食")
    assert_equal(explicit_detail["kcal"], 223, "explicit kcal priority")
    trusted = app.estimate_calorie_detail("ファミチキ2個", "間食")
    assert_equal(trusted["kcal"], 503, "lookup quantity calculation")
    fallback = app.estimate_calorie_detail("見慣れない軽食", "間食")
    assert_equal(fallback["kcal"], 200, "existing fallback remains available")

    if subprocess.run(["git", "diff", "--quiet", "--", "records.csv"], cwd=ROOT, check=False).returncode:
        raise AssertionError("records.csv must remain unchanged")
    if "food_lookup" in (ROOT / "records.csv").read_text(encoding="utf-8-sig").splitlines()[0]:
        raise AssertionError("CSV schema must not include lookup fields")

    print("PR8.2 food lookup validation passed")


if __name__ == "__main__":
    main()
