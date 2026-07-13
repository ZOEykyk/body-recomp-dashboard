from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bodyos_standard import SCORE_COMPONENTS, SCORE_COMPONENT_MAXIMA, calculate_bodyos_score
from dashboard import achievement_rate, component_trend, seven_day_average_percentage


def assert_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0001):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def base_component_frame(days: int) -> pd.DataFrame:
    data = pd.DataFrame({"日付": pd.date_range("2026-07-01", periods=days)})
    for component in SCORE_COMPONENTS:
        data[component] = SCORE_COMPONENT_MAXIMA[component]
    return data


def validate_component_maxima() -> None:
    expected = {
        "体重スコア": 15,
        "食事スコア": 20,
        "タンパク質スコア": 15,
        "歩数スコア": 10,
        "筋トレスコア": 10,
        "睡眠スコア": 10,
        "体調スコア": 10,
        "飲酒スコア": 10,
    }
    if SCORE_COMPONENT_MAXIMA != expected:
        raise AssertionError(f"component maxima mismatch: {SCORE_COMPONENT_MAXIMA}")
    if set(SCORE_COMPONENTS) != set(SCORE_COMPONENT_MAXIMA):
        raise AssertionError("all score components must have maximum-score metadata")
    if sum(SCORE_COMPONENT_MAXIMA.values()) != 100:
        raise AssertionError("component maximum scores should sum to 100")


def validate_normalization() -> None:
    assert_close(achievement_rate(10, 10), 100.0, "10/10 normalization")
    assert_close(achievement_rate(10, 20), 50.0, "10/20 normalization")
    assert_close(achievement_rate(999, 20), 100.0, "normalization upper bound")
    assert_close(achievement_rate(-5, 20), 0.0, "normalization lower bound")
    if achievement_rate(None, 10) is not None or achievement_rate("", 10) is not None:
        raise AssertionError("missing values should remain missing, not become 0%")


def validate_seven_day_average_and_trend() -> None:
    short = base_component_frame(3)
    short["食事スコア"] = [10, 15, 20]
    assert_close(seven_day_average_percentage(short, "食事スコア"), 75.0, "short seven-day average")
    if component_trend(short, "食事スコア") != "データ不足":
        raise AssertionError("less than eight valid records should show insufficient trend data")

    with_missing = base_component_frame(5)
    with_missing["睡眠スコア"] = [None, None, None, None, None]
    if seven_day_average_percentage(with_missing, "睡眠スコア") is not None:
        raise AssertionError("missing component values should be excluded from averages")

    improving = base_component_frame(10)
    improving["歩数スコア"] = [3, 3, 3, 8, 8, 8, 8, 9, 9, 9]
    if component_trend(improving, "歩数スコア") != "↑ improving":
        raise AssertionError("recent average should show improving trend")


def validate_body_score_unchanged() -> None:
    record = {
        "体重": 83.0,
        "推定摂取カロリー": 1900,
        "朝": "プロテイン",
        "昼": "鶏むね肉",
        "夜": "納豆",
        "歩数": 10000,
        "筋トレ有無": "あり",
        "睡眠時間": 7,
        "体調": "良い",
        "飲酒": "なし",
    }
    result = calculate_bodyos_score(record)
    component_total = sum(result["overall"]["components"].values())
    if result["Body Score"] != component_total:
        raise AssertionError("Body Score should remain the sum of raw component scores")
    if result["overall"]["max_score"] != 100:
        raise AssertionError("Body Score max score should remain 100")


def main() -> None:
    validate_component_maxima()
    validate_normalization()
    validate_seven_day_average_and_trend()
    validate_body_score_unchanged()
    print("PR7.2 validation passed")


if __name__ == "__main__":
    main()
