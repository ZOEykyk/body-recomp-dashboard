from __future__ import annotations

from copy import deepcopy
import datetime as dt
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from food_lookup import lookup_food, lookup_parsed_foods
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


def main() -> None:
    famichiki = parse_food_text("ファミマ ファミチキ2個", "間食")["items"][0]
    before_item = deepcopy(famichiki)
    famichiki_result = lookup_food(famichiki)
    assert_equal(famichiki, before_item, "lookup input mutation")
    assert_equal(famichiki_result["matched"], True, "famichiki matched")
    assert_equal(famichiki_result["match"]["strategy"], "brand_exact", "famichiki brand match")
    assert_equal(famichiki_result["nutrition"]["calories_kcal"], 251.7, "famichiki kcal")
    assert_equal(famichiki_result["nutrition"]["basis"], "per_item", "famichiki basis")
    assert_equal(famichiki_result["source"]["source_type"], "official_product_page", "famichiki source")

    unbranded_famichiki = parse_food_text("ファミチキ", "間食")["items"][0]
    assert_equal(
        lookup_food(unbranded_famichiki)["match"]["strategy"],
        "canonical_exact",
        "unbranded canonical match",
    )

    breakfast = parse_food_text("ソーセージエッグマフィン、ハッシュポテト", "朝")
    before_parsed = deepcopy(breakfast)
    breakfast_results = lookup_parsed_foods(breakfast)
    assert_equal(breakfast, before_parsed, "parsed foods mutation")
    assert_equal(breakfast_results["matched_count"], 2, "mcdonalds seed matches")
    assert_equal(
        [item["food"]["canonical_name"] for item in breakfast_results["items"]],
        ["ソーセージエッグマフィン", "ハッシュポテト"],
        "canonical result names",
    )

    red = parse_food_text("ファミチキ レッド", "間食")["items"][0]
    assert_equal(lookup_food(red)["matched"], False, "variant must not use base product")

    unknown = parse_food_text("おばあちゃん特製カレー", "夜")["items"][0]
    unknown_result = lookup_food(unknown)
    assert_equal(unknown_result["matched"], False, "unresolved food remains unresolved")
    assert_equal(unknown_result["match"]["confidence"], "low", "unresolved confidence")

    install_fake_streamlit()
    import app

    explicit = app.estimate_calorie_detail("ファミチキ2個、1個あたり223kcal", "間食")
    assert_equal(explicit["kcal"], 223, "explicit kcal priority")
    trusted = app.estimate_calorie_detail("ファミチキ2個", "間食")
    assert_equal(trusted["kcal"], 503, "lookup quantity calculation")
    fallback = app.estimate_calorie_detail("見慣れない軽食", "間食")
    assert_equal(fallback["kcal"], 200, "existing fallback remains available")

    print("PR8.2 food lookup validation passed")


if __name__ == "__main__":
    main()
