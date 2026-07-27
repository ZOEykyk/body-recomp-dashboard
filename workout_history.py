from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import pandas as pd


def parse_json_column(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    if value is None:
        return deepcopy(default)
    try:
        if pd.isna(value):
            return deepcopy(default)
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return deepcopy(default)
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return deepcopy(default)
    return parsed


def structured_workout(row: dict[str, Any] | pd.Series) -> dict[str, Any] | None:
    parsed = parse_json_column(row.get("構造化筋トレJSON"), None)
    return parsed if isinstance(parsed, dict) else None


def workout_history_rows(data: pd.DataFrame) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for _, row in data.sort_values("日付", ascending=False).iterrows():
        workout = structured_workout(row)
        if not isinstance(workout, dict) or not workout.get("performed"):
            continue
        duration = workout.get("duration_minutes")
        for exercise in workout.get("exercises") or []:
            sets = exercise.get("sets") or []
            set_text = " / ".join(
                (
                    f"{item.get('weight_kg'):g}kg×{item.get('reps')}"
                    if item.get("weight_kg") is not None and item.get("reps") is not None
                    else f"{item.get('reps')}回"
                    if item.get("reps") is not None
                    else "—"
                )
                for item in sets
                if isinstance(item, dict)
            )
            history.append(
                {
                    "日付": pd.to_datetime(row.get("日付"), errors="coerce").strftime("%Y-%m-%d"),
                    "プログラム": workout.get("program_name") or "—",
                    "時間": f"{float(duration):g}分" if duration is not None else "—",
                    "種目": exercise.get("name") or "—",
                    "重量・回数": set_text or "—",
                    "セット数": len(sets),
                }
            )
    return history


__all__ = ["parse_json_column", "structured_workout", "workout_history_rows"]
