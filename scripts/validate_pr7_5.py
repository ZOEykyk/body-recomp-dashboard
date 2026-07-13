from __future__ import annotations

import datetime as dt
import math
import sys
import types
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_integrity import format_weight_kg, is_missing_numeric, is_zero_meal_text, valid_weight_series


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


def assert_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0001):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def validate_weight_rules() -> None:
    mixed = valid_weight_series(pd.Series([83.5, 83.3, None, 83.4, 0, "0", "invalid", 83.6]))
    assert_close(float(mixed.mean()), (83.5 + 83.3 + 83.4 + 83.6) / 4, "mixed valid/null/zero weight average")

    all_missing = valid_weight_series(pd.Series([None, "", 0, "0", float("nan"), "invalid"]))
    if not pd.isna(all_missing.mean()):
        raise AssertionError("entire missing week should have no average")

    one_valid = valid_weight_series(pd.Series([None, 84.2, 0]))
    assert_close(float(one_valid.mean()), 84.2, "one valid record average")

    if format_weight_kg(0) != "—" or format_weight_kg(None) != "—":
        raise AssertionError("missing daily weight should display as dash")

    if is_missing_numeric("83.5kg") or not is_missing_numeric("abc123"):
        raise AssertionError("weight parsing should accept kg suffix but reject invalid non-numeric text")


def validate_zero_meal_rules() -> None:
    zero_meals = [
        None,
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
    ]
    for text in zero_meals:
        if not is_zero_meal_text(text):
            raise AssertionError(f"zero meal text was not recognized: {text!r}")

    if is_zero_meal_text("飲み会で軽く食べた"):
        raise AssertionError("unknown non-empty meal must still allow fallback estimation")


def validate_app_integration() -> None:
    install_fake_streamlit()
    import app

    for meal_type in ["朝", "昼", "夜", "間食"]:
        detail = app.estimate_calorie_detail("なし", meal_type)
        if detail["kcal"] != 0 or detail["confidence"] != "high":
            raise AssertionError(f"{meal_type} zero meal should be 0 kcal/high confidence: {detail}")

    fallback_detail = app.estimate_calorie_detail("飲み会で軽く食べた", "夜")
    if fallback_detail["kcal"] <= 0:
        raise AssertionError("unknown non-empty dinner should still allow fallback calories")

    normalized = app.normalize_record({"date": "2026-07-13", "weight": "invalid", "meals": {"dinner": "なし"}})
    if normalized["体重"] != 0:
        raise AssertionError("invalid imported weight should be stored as missing-compatible 0")
    if normalized["夜カロリー(kcal)"] != 0:
        raise AssertionError("imported dinner 'なし' should be 0 kcal")

    prediction_data = pd.DataFrame(
        {
            "日付": pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]),
            "体重": [83.5, 0, None, 83.0],
        }
    )
    prediction = app.predict_target_date(prediction_data, 76.0)
    if "予測には2件以上" in prediction:
        raise AssertionError("target prediction should use valid weights and ignore missing entries")


def main() -> None:
    validate_weight_rules()
    validate_zero_meal_rules()
    validate_app_integration()
    print("PR7.5 validation passed")


if __name__ == "__main__":
    main()
