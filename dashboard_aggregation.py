from __future__ import annotations

from typing import Any

import pandas as pd

from data_integrity import parse_optional_positive_number
from workout_history import structured_workout


AGGREGATION_VERSION = "1.0"


def _optional_number(value: Any, *, allow_zero: bool = True) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or (number == 0 and not allow_zero):
        return None
    return number


def aggregate_record(row: dict[str, Any] | pd.Series) -> dict[str, Any]:
    """Project only persisted values; no food or workout re-estimation occurs here."""
    workout = structured_workout(row)
    exercises = workout.get("exercises") if isinstance(workout, dict) else []
    exercises = exercises if isinstance(exercises, list) else []
    derived_session_count = 1 if isinstance(workout, dict) and workout.get("performed") else 0
    derived_exercise_count = len(exercises)
    derived_set_count = sum(
        len(exercise.get("sets") or [])
        for exercise in exercises
        if isinstance(exercise, dict) and isinstance(exercise.get("sets") or [], list)
    )

    def stored_count(column: str, derived: int) -> int:
        value = _optional_number(row.get(column))
        return int(value) if value is not None else derived

    return {
        "metadata": {"dashboard_aggregation_version": AGGREGATION_VERSION},
        "date": row.get("日付"),
        "weight_kg": parse_optional_positive_number(row.get("体重")),
        "sleep_hours": _optional_number(row.get("睡眠時間")),
        "condition": _optional_number(row.get("体調")),
        "steps": _optional_number(row.get("歩数")),
        "calories_kcal": _optional_number(row.get("推定摂取カロリー")),
        "protein_g": _optional_number(row.get("タンパク質(g)")),
        "fat_g": _optional_number(row.get("脂質(g)")),
        "carbs_g": _optional_number(row.get("炭水化物(g)")),
        "unknown_calorie_count": stored_count("カロリー不明件数", 0),
        "alcohol": row.get("飲酒"),
        "workout": workout,
        "workout_performed": bool(
            derived_session_count
            or str(row.get("筋トレ有無") or "").strip() in {"あり", "有", "実施", "true", "True"}
        ),
        "workout_session_count": stored_count("筋トレセッション数", derived_session_count),
        "workout_exercise_count": stored_count("筋トレ種目数", derived_exercise_count),
        "workout_set_count": stored_count("筋トレセット数", derived_set_count),
        "workout_duration_minutes": _optional_number(
            row.get("筋トレ時間(分)")
            if row.get("筋トレ時間(分)") is not None
            else (workout or {}).get("duration_minutes")
        ),
    }


def aggregate_records(data: pd.DataFrame) -> pd.DataFrame:
    rows = [aggregate_record(row) for _, row in data.iterrows()]
    return pd.DataFrame(rows, index=data.index)


__all__ = [
    "AGGREGATION_VERSION",
    "aggregate_record",
    "aggregate_records",
]
