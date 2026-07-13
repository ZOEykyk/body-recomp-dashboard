from __future__ import annotations

import re
from typing import Any

BODYOS_STANDARD_VERSION = "1.0"
TARGET_WEIGHT = 76.0
MODES = ["NORMAL", "EVENT", "RECOVERY", "BULK"]

SCORE_COMPONENTS = [
    "体重スコア",
    "食事スコア",
    "タンパク質スコア",
    "歩数スコア",
    "筋トレスコア",
    "睡眠スコア",
    "体調スコア",
    "飲酒スコア",
]

SCORE_COMPONENT_MAXIMA = {
    "体重スコア": 15,
    "食事スコア": 20,
    "タンパク質スコア": 15,
    "歩数スコア": 10,
    "筋トレスコア": 10,
    "睡眠スコア": 10,
    "体調スコア": 10,
    "飲酒スコア": 10,
}

CONDITION_SCORES = {
    "最高": 5,
    "とても良い": 5,
    "良い": 4,
    "普通": 3,
    "やや悪い": 2,
    "悪い": 1,
    "不調": 1,
}

PROTEIN_KEYWORDS = [
    "プロテイン",
    "鶏",
    "チキン",
    "サラダチキン",
    "卵",
    "たまご",
    "オイコス",
    "ヨーグルト",
    "肉",
    "魚",
    "鮭",
    "ツナ",
    "豆腐",
    "納豆",
    "protein",
]


def parse_number(value: Any, default: float = 0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return default
    return float(match.group(0))


def get_nested_value(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def first_value(record: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = get_nested_value(record, key) if "." in key else record.get(key)
        if value is not None and value != "":
            return value
    return default


def normalize_mode(value: Any) -> str:
    text = str(value or "").strip().upper()
    mode_aliases = {
        "通常": "NORMAL",
        "通常日": "NORMAL",
        "イベント": "EVENT",
        "イベント日": "EVENT",
        "飲み会": "EVENT",
        "旅行": "EVENT",
        "体調不良": "RECOVERY",
        "二日酔い": "RECOVERY",
        "リカバリー": "RECOVERY",
        "増量": "BULK",
        "増量期": "BULK",
    }
    if text in MODES:
        return text
    return mode_aliases.get(str(value or "").strip(), "NORMAL")


def normalize_yes_no(value: Any) -> str:
    if value is None or value == "":
        return "なし"
    if isinstance(value, bool):
        return "あり" if value else "なし"
    if isinstance(value, dict):
        for key in ["performed", "trained", "done", "筋トレ有無", "実施"]:
            if key in value:
                return normalize_yes_no(value[key])
        return "あり" if any(str(item).strip() for item in value.values()) else "なし"

    text = str(value).strip()
    if not text:
        return "なし"
    lowered = text.lower()
    if lowered in {"true", "yes", "y", "1", "done"} or "true" in lowered:
        return "あり"
    if lowered in {"false", "no", "n", "0", "none", "なし", "休み", "してない"} or "false" in lowered:
        return "なし"
    if lowered in {"あり", "実施", "した"}:
        return "あり"
    if any(word in text for word in ["なし", "無", "休み", "してない"]):
        return "なし"
    if any(word in text for word in ["あり", "有", "実施", "した"]):
        return "あり"
    return text


def bounded_score(value: float, maximum: int) -> int:
    return int(round(max(0, min(maximum, value))))


def condition_score(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None

    numeric = parse_number(text, default=None)
    if numeric is not None and 0 <= numeric <= 100:
        if numeric <= 5:
            return numeric * 2
        if numeric <= 10:
            return numeric
        return numeric / 10

    for keyword, score in CONDITION_SCORES.items():
        if keyword in text:
            return float(score * 2)
    return None


def meal_text(record: dict[str, Any]) -> str:
    meals = record.get("meals")
    if isinstance(meals, dict):
        meal_values = [
            meals.get("breakfast"),
            meals.get("lunch"),
            meals.get("dinner"),
            meals.get("snacks"),
            meals.get("朝"),
            meals.get("昼"),
            meals.get("夜"),
            meals.get("間食"),
        ]
    else:
        meal_values = [meals]

    meal_values.extend(
        [
            record.get("朝"),
            record.get("昼"),
            record.get("夜"),
            record.get("間食"),
            record.get("breakfast"),
            record.get("lunch"),
            record.get("dinner"),
            record.get("snacks"),
            record.get("仕事中のドリンク"),
            record.get("drinks"),
        ]
    )
    return " ".join(str(value or "") for value in meal_values)


def protein_score_from_text(*values: Any) -> int:
    text = " ".join(str(value or "") for value in values)
    hits = sum(1 for keyword in PROTEIN_KEYWORDS if keyword.lower() in text.lower())
    if hits >= 3:
        return 15
    if hits == 2:
        return 12
    if hits == 1:
        return 8
    return 3 if text.strip() else 0


def calorie_score(calories: float, mode: str) -> int:
    if mode == "EVENT":
        if 1500 <= calories <= 3200:
            return 20
        if calories <= 3800:
            return 16
        return 11
    if mode == "RECOVERY":
        if 1400 <= calories <= 2800:
            return 18
        if calories <= 3400:
            return 14
        return 10
    if mode == "BULK":
        if 2200 <= calories <= 3200:
            return 18
        if 1800 <= calories <= 3600:
            return 14
        return 10

    if 1600 <= calories <= 2300:
        return 20
    if 2300 < calories <= 2700 or 1300 <= calories < 1600:
        return 15
    if 2700 < calories <= 3200:
        return 10
    return 6 if calories > 0 else 0


def weight_score(weight: float, mode: str) -> int:
    if weight <= 0:
        return 0
    if mode == "RECOVERY":
        return bounded_score(14 - max(0, weight - TARGET_WEIGHT) * 0.3, 15)
    if mode == "BULK":
        return bounded_score(12, 15)
    return bounded_score(15 - max(0, weight - TARGET_WEIGHT) * 0.4, 15)


def steps_score(steps: float, mode: str) -> int:
    if mode == "RECOVERY":
        if steps >= 6000:
            return 10
        if steps >= 3000:
            return 8
        return 6 if steps > 0 else 4
    if steps >= 12000:
        return 10
    if steps >= 10000:
        return 9
    if steps >= 8000:
        return 8
    if steps >= 6000:
        return 6
    return 3 if steps > 0 else 0


def training_score(trained: Any, mode: str) -> int:
    did_train = normalize_yes_no(trained) == "あり"
    if mode == "RECOVERY":
        return 10 if not did_train else 8
    if mode == "EVENT":
        return 10 if did_train else 7
    if mode == "BULK":
        return 10 if did_train else 4
    return 10 if did_train else 0


def sleep_score(hours: float, mode: str) -> int:
    if mode == "RECOVERY":
        if hours >= 8:
            return 10
        if hours >= 7:
            return 8
        if hours >= 6:
            return 6
        return 3 if hours > 0 else 0
    if 7 <= hours <= 9:
        return 10
    if 6 <= hours < 7 or 9 < hours <= 10:
        return 8
    if 5 <= hours < 6:
        return 5
    if mode == "EVENT":
        return 4 if hours > 0 else 0
    return 2 if hours > 0 else 0


def health_score(condition: Any, mode: str) -> int:
    parsed = condition_score(condition)
    if parsed is None:
        return 6 if mode in {"EVENT", "RECOVERY"} else 0
    return bounded_score(parsed, 10)


def alcohol_level_from_text(alcohol: Any, detail: Any = "", level: Any = "") -> str:
    combined = " ".join(str(value or "") for value in [alcohol, detail, level]).strip().lower()
    if not combined or combined in {"なし", "無", "no", "n", "false", "0"}:
        return "none"
    if any(keyword in combined for keyword in ["濃い", "7杯", "8杯", "9杯", "10杯", "二日酔い", "翌日", "heavy", "high", "多量"]):
        return "heavy"
    if any(keyword in combined for keyword in ["通常", "普通", "3杯", "4杯", "5杯", "6杯", "medium", "middle"]):
        return "regular"
    if any(keyword in combined for keyword in ["軽", "少", "1杯", "2杯", "light", "low"]):
        return "light"
    if any(keyword in combined for keyword in ["あり", "有", "ビール", "ハイボール", "酒", "飲"]):
        return "regular"
    return "none"


def alcohol_score(alcohol: Any, detail: Any = "", level: Any = "") -> int:
    level_name = alcohol_level_from_text(alcohol, detail, level)
    return {
        "none": 10,
        "light": 8,
        "regular": 5,
        "heavy": 2,
    }[level_name]


def calculate_bodyos_score(record: dict[str, Any]) -> dict[str, Any]:
    """Calculate BodyOS Standard v1.0 daily score without mutating the input record."""
    mode = normalize_mode(first_value(record, "モード", "mode", default="NORMAL"))
    workout = record.get("workout") if isinstance(record.get("workout"), dict) else {}
    trained = first_value(record, "筋トレ有無", "trained", "performed", "workout.performed", default=workout)
    calories = first_value(record, "推定摂取カロリー", "calories", "kcal", "total_kcal", default=0)
    steps_value = parse_number(first_value(record, "歩数", "steps", default=0))
    sleep_hours = parse_number(first_value(record, "睡眠時間", "sleep", "sleep_hours", default=0))
    condition = first_value(record, "体調", "condition", "health", default="")
    alcohol = first_value(record, "飲酒", "alcohol", "drinking", "drank_alcohol", default="")
    alcohol_detail = first_value(record, "飲酒内容", "alcohol_detail", default="")
    alcohol_level = first_value(record, "飲酒レベル", "alcohol_level", "drinking_level", default="")

    components = {
        "体重スコア": weight_score(parse_number(first_value(record, "体重", "weight", "weight_kg", default=0)), mode),
        "食事スコア": calorie_score(parse_number(calories, default=0), mode),
        "タンパク質スコア": protein_score_from_text(meal_text(record)),
        "歩数スコア": steps_score(steps_value, mode),
        "筋トレスコア": training_score(trained, mode),
        "睡眠スコア": sleep_score(sleep_hours, mode),
        "体調スコア": health_score(condition, mode),
        "飲酒スコア": alcohol_score(alcohol, alcohol_detail, alcohol_level),
    }
    total = sum(components.values())
    alcohol_level_name = alcohol_level_from_text(alcohol, alcohol_detail, alcohol_level)
    did_train = normalize_yes_no(trained) == "あり"

    evaluation = {
        "metadata": {
            "bodyos_standard_version": BODYOS_STANDARD_VERSION,
            "mode": mode,
            "pure_function": True,
        },
        "overall": {
            "score": total,
            "max_score": sum(SCORE_COMPONENT_MAXIMA.values()),
            "components": components,
            "component_max_scores": SCORE_COMPONENT_MAXIMA.copy(),
        },
        "steps": {
            "value": steps_value,
            "score": components["歩数スコア"],
        },
        "sleep": {
            "hours": sleep_hours,
            "score": components["睡眠スコア"],
        },
        "nutrition": {
            "calories": parse_number(calories, default=0),
            "score": components["食事スコア"],
            "protein_score": components["タンパク質スコア"],
        },
        "workout": {
            "performed": did_train,
            "score": components["筋トレスコア"],
        },
        "recovery": {
            "condition": condition,
            "condition_score": components["体調スコア"],
            "alcohol_level": alcohol_level_name,
            "alcohol_score": components["飲酒スコア"],
            "score": components["体調スコア"] + components["飲酒スコア"],
        },
        "coach": {
            "comment": first_value(record, "コメント", "comment", "coach_comment", default=""),
            "signals": [],
        },
    }

    return {
        **evaluation,
        # Compatibility fields for the current Streamlit app and records.csv columns.
        "bodyos_standard_version": BODYOS_STANDARD_VERSION,
        "mode": mode,
        "components": components,
        "Body Score": total,
        **components,
    }
