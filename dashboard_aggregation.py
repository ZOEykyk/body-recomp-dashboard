from __future__ import annotations

import ast
import json
from typing import Any

import pandas as pd

from data_integrity import parse_optional_positive_number
from workout_history import structured_workout


AGGREGATION_VERSION = "1.0"
DASHBOARD_PROJECTION_VERSION = "1.0"
MEAL_PROJECTION_CONFIG = {
    "breakfast": {"label": "朝", "legacy_column": "朝", "calorie_column": "朝カロリー(kcal)"},
    "lunch": {"label": "昼", "legacy_column": "昼", "calorie_column": "昼カロリー(kcal)"},
    "snacks": {"label": "間食", "legacy_column": "間食", "calorie_column": "間食カロリー(kcal)"},
    "dinner": {"label": "夜", "legacy_column": "夜", "calorie_column": "夜カロリー(kcal)"},
    "drinks": {
        "label": "仕事中のドリンク",
        "legacy_column": "仕事中のドリンク",
        "calorie_column": "ドリンクカロリー(kcal)",
    },
}


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


def _is_missing_display_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "none", "null", "[]", "{}"}
    return False


def _decode_collection(value: Any) -> Any:
    if isinstance(value, (list, tuple, dict)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{" or text[-1] not in "]}":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return value


def display_text(value: Any, *, empty: str = "—", separator: str = " ／ ") -> str:
    parsed = _decode_collection(value)
    if _is_missing_display_value(parsed):
        return empty
    if isinstance(parsed, dict):
        text = parsed.get("name") or parsed.get("text")
        return display_text(text, empty=empty, separator=separator)
    if isinstance(parsed, (list, tuple, set)):
        parts = [
            display_text(item, empty="", separator=separator)
            for item in parsed
        ]
        return separator.join(part for part in parts if part) or empty
    text = str(parsed).strip()
    if _is_missing_display_value(text):
        return empty
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return separator.join(lines) if len(lines) > 1 else text


def _decode_structured_meals(value: Any) -> dict[str, Any]:
    parsed = _decode_collection(value)
    return parsed if isinstance(parsed, dict) else {}


def _meal_section(structured: dict[str, Any], meal_type: str) -> tuple[bool, Any]:
    aliases = (meal_type, "snack") if meal_type == "snacks" else (meal_type,)
    for key in aliases:
        if key in structured:
            return True, structured.get(key)
    return False, None


def _section_items(section: Any) -> list[dict[str, Any]]:
    if isinstance(section, list):
        values = section
    elif isinstance(section, dict):
        values = section.get("items") if isinstance(section.get("items"), list) else []
    else:
        values = []
    return [item for item in values if isinstance(item, dict)]


def _legacy_meal_names(value: Any) -> list[str]:
    parsed = _decode_collection(value)
    if _is_missing_display_value(parsed):
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    if isinstance(parsed, (list, tuple)):
        names = []
        for item in parsed:
            if isinstance(item, dict):
                name = display_text(item.get("name"), empty="")
            else:
                name = display_text(item, empty="")
            if name:
                names.append(name)
        return names
    text = display_text(parsed, empty="")
    return [text] if text else []


def _item_calories(item: dict[str, Any]) -> float | None:
    explicit = item.get("nutrition")
    if isinstance(explicit, dict) and str(explicit.get("basis") or "") == "total":
        value = _optional_number(explicit.get("calories_kcal"))
        if value is not None:
            return value
    resolved = item.get("resolved_nutrition")
    if isinstance(resolved, dict):
        return _optional_number(resolved.get("calories_kcal"))
    return None


def _format_number(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}".rstrip("0").rstrip(".")


def _meal_calorie_display(calories: float | None, unknown_count: int) -> str:
    if calories is None:
        return f"—（不明{unknown_count}件）" if unknown_count else "—"
    known = f"{_format_number(calories)}kcal"
    return f"{known}（既知分・不明{unknown_count}件）" if unknown_count else known


def _project_meal(row: dict[str, Any] | pd.Series, structured: dict[str, Any], meal_type: str) -> dict[str, Any]:
    config = MEAL_PROJECTION_CONFIG[meal_type]
    has_structured, section = _meal_section(structured, meal_type)
    if has_structured:
        items = _section_items(section)
        names = [
            display_text(item.get("name"), empty="")
            for item in items
        ]
        names = [name for name in names if name]
        totals = section.get("totals") if isinstance(section, dict) and isinstance(section.get("totals"), dict) else {}
        calories = _optional_number(totals.get("calories_kcal"))
        item_calories = [_item_calories(item) for item in items]
        if calories is None and any(value is not None for value in item_calories):
            calories = sum(value for value in item_calories if value is not None)
        unknown_count = sum(1 for value in item_calories if value is None)
        source = "structured"
    else:
        names = _legacy_meal_names(row.get(config["legacy_column"]))
        calories = _optional_number(row.get(config["calorie_column"]))
        unknown_count = 0
        items = [{"name": name, "quantity": None, "unit": None} for name in names]
        source = "legacy"
    return {
        "meal_type": meal_type,
        "label": config["label"],
        "source": source,
        "items": items,
        "names": names,
        "item_count": len(names),
        "display_text": "、".join(names) if names else "なし",
        "calories_kcal": calories,
        "unknown_calorie_count": unknown_count,
        "calorie_display": _meal_calorie_display(calories, unknown_count),
    }


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


def project_dashboard_record(row: dict[str, Any] | pd.Series) -> dict[str, Any]:
    """Create the complete, display-safe record consumed by dashboard UI."""
    aggregate = aggregate_record(row)
    structured_meals = _decode_structured_meals(row.get("構造化食事JSON"))
    meals = {
        meal_type: _project_meal(row, structured_meals, meal_type)
        for meal_type in MEAL_PROJECTION_CONFIG
    }
    known_meal_calories = [
        meal["calories_kcal"]
        for meal in meals.values()
        if meal["calories_kcal"] is not None
    ]
    known_meal_total = sum(known_meal_calories) if known_meal_calories else None
    daily_calories = aggregate["calories_kcal"]
    projection = {
        "metadata": {
            "dashboard_projection_version": DASHBOARD_PROJECTION_VERSION,
            "meal_source": "structured" if structured_meals else "legacy",
        },
        **aggregate,
        "meals": meals,
        "meal_item_count": sum(meal["item_count"] for meal in meals.values()),
        "known_meal_calories_kcal": known_meal_total,
        "meal_calories_match_daily": (
            daily_calories is None
            or known_meal_total is None
            or abs(daily_calories - known_meal_total) < 0.01
        ),
        "calorie_confidence": display_text(row.get("カロリー推定信頼度")),
        "workout_status": "あり" if aggregate["workout_performed"] else "なし",
        "workout_detail": display_text(row.get("筋トレ内容")),
        "mode": display_text(row.get("モード")),
        "event_name": display_text(row.get("イベント名")),
        "body_score": _optional_number(row.get("Body Score")),
        "component_scores": {
            "タンパク質スコア": _optional_number(row.get("タンパク質スコア")),
        },
        "condition_display": display_text(row.get("体調")),
        "alcohol": display_text(row.get("飲酒"), empty="なし"),
        "alcohol_detail": display_text(row.get("飲酒内容"), empty="なし"),
        "daily_score": _optional_number(row.get("今日の採点")),
        "notes": display_text(row.get("コメント")),
    }
    projection["recent_detail_lines"] = [
        *[
            f"{meals[meal_type]['label']}: {meals[meal_type]['display_text']} / "
            f"{meals[meal_type]['calorie_display']}"
            for meal_type in ("breakfast", "lunch", "snacks", "dinner", "drinks")
        ],
        f"カロリー推定信頼度: {projection['calorie_confidence']}",
        (
            f"筋トレ: {projection['workout_status']} / "
            f"{projection['workout_session_count']}セッション・"
            f"{projection['workout_exercise_count']}種目・{projection['workout_set_count']}セット / "
            f"{projection['workout_detail']}"
        ),
        (
            f"モード: {projection['mode']} / イベント名: {projection['event_name']} / "
            f"Body Score: {_format_number(projection['body_score'])}"
        ),
        (
            f"体調: {projection['condition_display']} / 飲酒: {projection['alcohol']} / "
            f"飲酒内容: {projection['alcohol_detail']} / 採点: {_format_number(projection['daily_score'])}"
        ),
        f"コメント: {projection['notes']}",
    ]
    projection["history_display"] = {
        "モード": projection["mode"],
        "イベント名": projection["event_name"],
        "筋トレ有無": projection["workout_status"],
        "飲酒": projection["alcohol"],
        "飲酒内容": projection["alcohol_detail"],
        "コメント": projection["notes"],
    }
    return projection


def aggregate_records(data: pd.DataFrame) -> pd.DataFrame:
    rows = [aggregate_record(row) for _, row in data.iterrows()]
    return pd.DataFrame(rows, index=data.index)


__all__ = [
    "AGGREGATION_VERSION",
    "DASHBOARD_PROJECTION_VERSION",
    "aggregate_record",
    "aggregate_records",
    "display_text",
    "project_dashboard_record",
]
