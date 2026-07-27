from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard_aggregation import aggregate_record, aggregate_records  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    csv_path = ROOT / "records.csv"
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    workout = {
        "performed": True,
        "duration_minutes": 75,
        "exercises": [
            {"name": "Press", "sets": [{"weight_kg": 32, "reps": 10}, {"weight_kg": 32, "reps": 9}]},
        ],
    }
    row = {
        "日付": pd.Timestamp("2026-07-26"),
        "体重": 83.2,
        "睡眠時間": 8,
        "体調": 8,
        "歩数": 11786,
        "推定摂取カロリー": 2200,
        "タンパク質(g)": 145,
        "脂質(g)": 65,
        "炭水化物(g)": 248,
        "カロリー不明件数": 2,
        "筋トレ有無": "あり",
        "筋トレセッション数": 1,
        "筋トレ種目数": 1,
        "筋トレセット数": 2,
        "筋トレ時間(分)": 75,
        "構造化筋トレJSON": json.dumps(workout, ensure_ascii=False),
        "飲酒": "なし",
    }
    aggregate = aggregate_record(row)
    check(aggregate["weight_kg"] == 83.2, "dashboard weight equals stored value")
    check(aggregate["steps"] == 11786, "dashboard steps equal stored value")
    check(aggregate["calories_kcal"] == 2200, "dashboard calories equal stored value")
    check(aggregate["protein_g"] == 145, "dashboard protein equals stored value")
    check(aggregate["unknown_calorie_count"] == 2, "dashboard exposes unknown calorie count")
    check(aggregate["workout_session_count"] == 1, "dashboard session count equals stored value")
    check(aggregate["workout_exercise_count"] == 1, "dashboard exercise count equals stored value")
    check(aggregate["workout_set_count"] == 2, "dashboard set count equals stored value")

    missing = aggregate_record(
        {
            "体重": None,
            "睡眠時間": None,
            "体調": None,
            "歩数": None,
            "推定摂取カロリー": None,
            "筋トレ有無": "",
        }
    )
    check(missing["weight_kg"] is None, "missing weight is not zero")
    check(missing["calories_kcal"] is None, "missing calories remain unknown")
    check(not missing["workout_performed"], "missing workout is not performed")

    frame = aggregate_records(pd.DataFrame([row, {**row, "日付": pd.Timestamp("2026-07-27"), "歩数": 9000}]))
    check(frame["steps"].tolist() == [11786.0, 9000.0], "batch aggregate uses the same record contract")
    after = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    check(before == after, "records.csv is unchanged")
    print("PR13 dashboard validation passed.")


if __name__ == "__main__":
    main()
