from __future__ import annotations

from copy import deepcopy
import datetime as dt
import hashlib
import json
import math
import re
import time
from typing import Any, Callable, Iterable
from uuid import uuid4

from data_integrity import is_zero_meal_text
from food_lookup import calculate_lookup_total
from workout_intelligence import parse_workout_detail


IMPORT_SCHEMA_VERSION = "1.0"
IMPORT_ENGINE_VERSION = "1.0"
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snacks", "drinks")
MEAL_LABELS = {
    "breakfast": "朝",
    "lunch": "昼",
    "dinner": "夜",
    "snacks": "間食",
    "drinks": "仕事中のドリンク",
}
TRUSTED_RESOLUTION_ORIGINS = {"personal", "official", "generic"}
NUTRITION_FIELDS = ("calories_kcal", "protein_g", "fat_g", "carbs_g")

ANOMALY_THRESHOLDS = {
    "weight_min_kg": 30,
    "weight_max_kg": 300,
    "sleep_max_hours": 24,
    "steps_max": 100_000,
    "calories_max_kcal": 10_000,
    "condition_min": 0,
    "condition_max": 10,
    "duplicate_food_count": 10,
}

LEGACY_KEYS = {
    "date": ("date", "日付", "record_date", "記録日"),
    "weight": ("weight", "weight_kg", "体重", "体重(kg)"),
    "sleep": ("sleep", "sleep_hours", "睡眠", "睡眠時間"),
    "condition": ("condition", "health", "体調"),
    "steps": ("steps", "歩数"),
    "notes": ("notes", "comment", "memo", "コメント", "メモ"),
    "mode": ("mode", "モード"),
    "event_name": ("event_name", "event", "イベント名"),
}
LEGACY_MEAL_KEYS = {
    "breakfast": ("breakfast", "朝", "朝食"),
    "lunch": ("lunch", "昼", "昼食"),
    "dinner": ("dinner", "夜", "夕食", "晩ごはん", "meal"),
    "snacks": ("snacks", "snack", "間食"),
    "drinks": ("drinks", "work_drinks", "ドリンク", "仕事中のドリンク"),
}


class ImportValidationError(ValueError):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = list(errors)
        self.warnings = list(warnings or [])
        super().__init__("\n".join(self.errors))


def _first(mapping: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        match = re.fullmatch(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        number = float(text)
    return number if math.isfinite(number) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _date(value: Any) -> str | None:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    try:
        return dt.date.fromisoformat(str(value).strip()).isoformat()
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _notes_text(value: Any) -> str | None:
    if isinstance(value, list):
        lines = [text for item in value if (text := _text(item))]
        return "\n".join(lines) or None
    return _text(value)


def _nutrition(value: Any, path: str, errors: list[str]) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(f"{path}: nutritionはobjectまたはnullにしてください。")
        return None
    aliases = {
        "calories_kcal": ("calories_kcal", "calories", "kcal"),
        "protein_g": ("protein_g", "protein", "P"),
        "fat_g": ("fat_g", "fat", "F"),
        "carbs_g": ("carbs_g", "carbohydrates_g", "carbs", "carbohydrates", "C"),
    }
    result: dict[str, Any] = {}
    for field, keys in aliases.items():
        raw = _first(value, keys)
        number = _number(raw)
        if raw is not None and (number is None or number < 0):
            errors.append(f"{path}.{field}: 0以上の数値またはnullにしてください。")
        result[field] = number if number is not None and number >= 0 else None
    basis = _text(value.get("basis")) or "unknown"
    allowed = {"per_item", "per_package", "per_serving", "per_100g", "per_100ml", "total", "unknown"}
    if basis not in allowed:
        errors.append(f"{path}.basis: 未対応の値です（{basis}）。")
        basis = "unknown"
    result["basis"] = basis
    return result


def _meal_item(value: Any, path: str, errors: list[str], warnings: list[str]) -> dict[str, Any] | None:
    if isinstance(value, str):
        name = value.strip()
        if not name or is_zero_meal_text(name):
            return None
        return {
            "name": name,
            "quantity": None,
            "quantity_text": None,
            "unit": None,
            "notes": None,
            "nutrition": None,
        }
    if not isinstance(value, dict):
        errors.append(f"{path}: 食品は文字列またはobjectにしてください。")
        return None

    name = _text(_first(value, ("name", "food_name", "text", "食品名", "name")))
    if not name:
        errors.append(f"{path}.name: 食品名が必要です。")
        return None
    raw_quantity = value.get("quantity")
    quantity_value = raw_quantity.get("value") if isinstance(raw_quantity, dict) else raw_quantity
    quantity = _number(quantity_value)
    quantity_text = _text(value.get("quantity_text"))
    unit = _text(value.get("unit"))
    if isinstance(raw_quantity, dict):
        unit = unit or _text(raw_quantity.get("unit"))
    if quantity_value is not None and (quantity is None or quantity <= 0):
        quantity_text = quantity_text or str(quantity_value)
        quantity = None
        warnings.append(f"{path}.quantity: 自由記述は計算に使わず原文として保持しました。")

    raw_nutrition = value.get("nutrition")
    if raw_nutrition is None:
        direct_nutrition_keys = {
            "calories_kcal",
            "calories",
            "kcal",
            "protein_g",
            "protein",
            "fat_g",
            "fat",
            "carbs_g",
            "carbohydrates_g",
            "carbs",
            "carbohydrates",
        }
        if any(key in value for key in direct_nutrition_keys):
            raw_nutrition = {
                key: value.get(key)
                for key in direct_nutrition_keys
                if key in value
            }
            raw_nutrition["basis"] = _text(value.get("nutrition_basis") or value.get("basis")) or "total"
    return {
        "name": name,
        "quantity": quantity,
        "quantity_text": quantity_text,
        "unit": unit,
        "notes": _notes_text(value.get("notes")),
        "nutrition": _nutrition(raw_nutrition, f"{path}.nutrition", errors),
    }


def _meal_items(value: Any, path: str, errors: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    if value is None or (isinstance(value, str) and is_zero_meal_text(value)):
        return []
    values = value if isinstance(value, list) else [value]
    items: list[dict[str, Any]] = []
    for index, candidate in enumerate(values):
        item = _meal_item(candidate, f"{path}[{index}]", errors, warnings)
        if item:
            items.append(item)
    return items


def _workout_set(value: Any, path: str, errors: list[str]) -> dict[str, Any] | None:
    if isinstance(value, int):
        value = {"reps": value}
    if not isinstance(value, dict):
        errors.append(f"{path}: setはobjectにしてください。")
        return None
    weight = _number(value.get("weight_kg"))
    reps = _integer(value.get("reps"))
    rpe = _number(value.get("rpe"))
    if weight is not None and weight < 0:
        errors.append(f"{path}.weight_kg: 0以上にしてください。")
        weight = None
    if reps is not None and reps < 0:
        errors.append(f"{path}.reps: 0以上にしてください。")
        reps = None
    if rpe is not None and not 0 <= rpe <= 10:
        errors.append(f"{path}.rpe: 0から10にしてください。")
        rpe = None
    return {
        "weight_kg": weight,
        "reps": reps,
        "rpe": rpe,
        "completed": bool(value.get("completed", True)),
        "set_type": _text(value.get("set_type")),
    }


def _exercise(value: Any, path: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{path}: exerciseはobjectにしてください。")
        return None
    name = _text(_first(value, ("name", "exercise", "種目")))
    if not name:
        errors.append(f"{path}.name: 種目名が必要です。")
        return None
    raw_sets = value.get("sets")
    if raw_sets is None and isinstance(value.get("reps"), list):
        raw_sets = [{"weight_kg": value.get("weight_kg"), "reps": reps} for reps in value["reps"]]
    if raw_sets is None:
        raw_sets = []
    if not isinstance(raw_sets, list):
        errors.append(f"{path}.sets: 配列にしてください。")
        raw_sets = []
    sets = [
        parsed
        for index, item in enumerate(raw_sets)
        if (parsed := _workout_set(item, f"{path}.sets[{index}]", errors)) is not None
    ]
    return {
        "exercise_order": 0,
        "name": name,
        "equipment": _text(value.get("equipment")),
        "notes": _text(value.get("notes")),
        "sets": [{**item, "set_order": index + 1} for index, item in enumerate(sets)],
    }


def _workout_from_text(text: str) -> dict[str, Any]:
    exercises: list[dict[str, Any]] = []
    for exercise_order, parsed in enumerate(parse_workout_detail(text), start=1):
        sets: list[dict[str, Any]] = []
        if parsed.get("work_sets"):
            for work_set in parsed["work_sets"]:
                for reps in work_set.get("reps") or []:
                    sets.append(
                        {
                            "set_order": len(sets) + 1,
                            "weight_kg": work_set.get("weight_kg"),
                            "reps": reps,
                            "rpe": None,
                            "completed": True,
                            "set_type": None,
                        }
                    )
        else:
            for reps in parsed.get("reps") or []:
                sets.append(
                    {
                        "set_order": len(sets) + 1,
                        "weight_kg": None,
                        "reps": reps,
                        "rpe": None,
                        "completed": True,
                        "set_type": None,
                    }
                )
        exercises.append(
            {
                "exercise_order": exercise_order,
                "name": parsed.get("exercise") or "unknown",
                "equipment": None,
                "notes": parsed.get("raw"),
                "sets": sets,
            }
        )
    return {
        "performed": bool(exercises),
        "program_name": None,
        "workout_type": None,
        "duration_minutes": None,
        "notes": text,
        "exercises": exercises,
    }


def _workout(value: Any, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    if value is None or value is False or (isinstance(value, str) and is_zero_meal_text(value)):
        return {
            "performed": False,
            "program_name": None,
            "workout_type": None,
            "duration_minutes": None,
            "notes": None,
            "exercises": [],
        }
    if isinstance(value, str):
        workout = _workout_from_text(value)
        if workout["performed"]:
            warnings.append("workout: 旧形式テキストをセット単位へ変換しました。")
        return workout
    if value is True:
        return {
            "performed": True,
            "program_name": None,
            "workout_type": None,
            "duration_minutes": None,
            "notes": None,
            "exercises": [],
        }
    if not isinstance(value, dict):
        errors.append("workout: object、boolean、文字列、nullのいずれかにしてください。")
        return _workout(None, [], [])

    raw_exercises = value.get("exercises") or []
    if isinstance(raw_exercises, dict):
        raw_exercises = [
            {"name": name, **(detail if isinstance(detail, dict) else {"reps": detail})}
            for name, detail in raw_exercises.items()
        ]
    if not isinstance(raw_exercises, list):
        errors.append("workout.exercises: 配列にしてください。")
        raw_exercises = []
    exercises = [
        parsed
        for index, item in enumerate(raw_exercises)
        if (parsed := _exercise(item, f"workout.exercises[{index}]", errors)) is not None
    ]
    for index, exercise in enumerate(exercises):
        exercise["exercise_order"] = index + 1
    duration = _integer(value.get("duration_minutes"))
    if duration is not None and duration < 0:
        errors.append("workout.duration_minutes: 0以上にしてください。")
        duration = None
    performed = value.get("performed")
    if performed is None:
        performed = bool(exercises)
    if not isinstance(performed, bool):
        errors.append("workout.performed: booleanにしてください。")
        performed = bool(exercises)
    return {
        "performed": performed,
        "program_name": _text(_first(value, ("program_name", "program", "種別"))),
        "workout_type": _text(value.get("workout_type")),
        "duration_minutes": duration,
        "notes": _text(_first(value, ("notes", "detail", "menu", "筋トレ内容"))),
        "exercises": exercises,
    }


def _legacy_workout(raw: dict[str, Any]) -> Any:
    value = _first(raw, ("workout", "training", "筋トレ"))
    detail = _first(raw, ("workout_detail", "training_detail", "筋トレ内容", "筋トレメニュー"))
    if isinstance(value, dict):
        return value
    if detail not in (None, ""):
        if isinstance(detail, dict) and not any(key in detail for key in ("exercises", "performed")):
            exercises = []
            program_name = _text(_first(detail, ("種別", "program_name")))
            for name, result in detail.items():
                if name in {"種別", "program_name"}:
                    continue
                exercises.append({"name": str(name), "sets": _sets_from_legacy_result(result)})
            return {"performed": True, "program_name": program_name, "exercises": exercises}
        return detail
    return value


def _sets_from_legacy_result(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [{"reps": reps} for reps in value]
    text = str(value or "")
    parsed = parse_workout_detail(f"exercise {text}")
    if not parsed:
        return []
    sets: list[dict[str, Any]] = []
    item = parsed[0]
    for work_set in item.get("work_sets") or []:
        sets.extend({"weight_kg": work_set.get("weight_kg"), "reps": reps} for reps in work_set.get("reps") or [])
    if not sets:
        sets.extend({"reps": reps} for reps in item.get("reps") or [])
    return sets


def _alcohol(value: Any, raw: dict[str, Any]) -> dict[str, Any]:
    detail = _text(_first(raw, ("alcohol_detail", "飲酒内容")))
    level = _text(_first(raw, ("alcohol_level", "飲酒レベル")))
    if isinstance(value, dict):
        consumed = value.get("consumed")
        return {
            "consumed": consumed if isinstance(consumed, bool) else None,
            "detail": _text(value.get("detail")) or detail,
            "level": _text(value.get("level")) or level,
        }
    if isinstance(value, bool):
        consumed = value
    else:
        text = str(value or "").strip().lower()
        consumed = None if not text else text not in {"false", "0", "no", "none", "なし", "無し", "未飲酒"}
    return {"consumed": consumed, "detail": detail, "level": level}


def _canonical_record(raw: dict[str, Any], record_number: int) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    schema_version = _text(raw.get("schema_version"))
    legacy = schema_version is None
    if not legacy:
        allowed_keys = {
            "schema_version",
            "date",
            "weight",
            "sleep",
            "condition",
            "steps",
            "meals",
            "alcohol",
            "workout",
            "notes",
            "mode",
            "event_name",
            "nutrition_totals",
        }
        unknown_keys = sorted(set(raw) - allowed_keys)
        if unknown_keys:
            errors.append(f"{record_number}件目: 未定義フィールドがあります（{', '.join(unknown_keys)}）。")
        if "meals" in raw and not isinstance(raw.get("meals"), dict):
            errors.append(f"{record_number}件目.meals: objectにしてください。")
        if isinstance(raw.get("sleep"), dict) and set(raw["sleep"]) - {"hours"}:
            errors.append(f"{record_number}件目.sleep: hours以外のフィールドは使用できません。")
    if schema_version is not None and schema_version != IMPORT_SCHEMA_VERSION:
        errors.append(
            f"{record_number}件目.schema_version: 未対応です（{schema_version}）。対応版は{IMPORT_SCHEMA_VERSION}です。"
        )
    if legacy:
        schema_version = IMPORT_SCHEMA_VERSION
        warnings.append(f"{record_number}件目: 旧JSONをschema_version 1.0へ変換しました。")

    date = _date(_first(raw, LEGACY_KEYS["date"]))
    if not date:
        errors.append(f"{record_number}件目.date: YYYY-MM-DD形式の日付が必要です。")

    def optional_number(name: str, minimum: float | None = None) -> float | None:
        value = _first(raw, LEGACY_KEYS[name])
        if name == "sleep" and isinstance(value, dict):
            value = value.get("hours")
        number = _number(value)
        if value is not None and number is None:
            errors.append(f"{record_number}件目.{name}: 数値またはnullにしてください。")
        if number is not None and minimum is not None and number < minimum:
            errors.append(f"{record_number}件目.{name}: {minimum}以上にしてください。")
            return None
        return number

    weight = optional_number("weight", 0)
    sleep = optional_number("sleep", 0)
    condition = optional_number("condition")
    steps_raw = _first(raw, LEGACY_KEYS["steps"])
    steps = _integer(steps_raw)
    if steps_raw is not None and steps is None:
        errors.append(f"{record_number}件目.steps: 整数またはnullにしてください。")

    raw_meals = raw.get("meals") if isinstance(raw.get("meals"), dict) else {}
    meals: dict[str, list[dict[str, Any]]] = {}
    missing_meal = object()
    for meal_type in MEAL_TYPES:
        source = _first(raw_meals, LEGACY_MEAL_KEYS[meal_type], missing_meal)
        if source is missing_meal:
            source = _first(raw, LEGACY_MEAL_KEYS[meal_type])
        meals[meal_type] = _meal_items(source, f"{record_number}件目.meals.{meal_type}", errors, warnings)

    workout = _workout(_legacy_workout(raw), errors, warnings)
    alcohol_raw = _first(raw, ("alcohol", "drinking", "drank_alcohol", "飲酒"))
    nutrition_totals = _nutrition(
        raw.get("nutrition_totals")
        or (
            {"calories_kcal": _first(raw, ("total_kcal", "calories", "kcal", "推定摂取カロリー"))}
            if _first(raw, ("total_kcal", "calories", "kcal", "推定摂取カロリー")) is not None
            else None
        ),
        f"{record_number}件目.nutrition_totals",
        errors,
    )
    provided_sections = {"date"}
    section_keys = {
        "weight": LEGACY_KEYS["weight"],
        "sleep": LEGACY_KEYS["sleep"],
        "condition": LEGACY_KEYS["condition"],
        "steps": LEGACY_KEYS["steps"],
        "notes": LEGACY_KEYS["notes"],
        "mode": LEGACY_KEYS["mode"],
        "event_name": LEGACY_KEYS["event_name"],
        "alcohol": ("alcohol", "drinking", "drank_alcohol", "飲酒", "alcohol_detail", "飲酒内容"),
        "workout": (
            "workout",
            "training",
            "筋トレ",
            "workout_detail",
            "training_detail",
            "筋トレ内容",
            "筋トレメニュー",
        ),
        "nutrition": ("nutrition_totals", "total_kcal", "calories", "kcal", "推定摂取カロリー"),
    }
    for section, keys in section_keys.items():
        if any(key in raw for key in keys):
            provided_sections.add(section)
    if "meals" in raw or any(any(key in raw for key in keys) for keys in LEGACY_MEAL_KEYS.values()):
        provided_sections.add("meals")

    if errors:
        raise ImportValidationError(errors, warnings)
    return (
        {
            "schema_version": schema_version,
            "date": date,
            "weight": weight,
            "sleep": {"hours": sleep},
            "condition": condition,
            "steps": steps,
            "meals": meals,
            "alcohol": _alcohol(alcohol_raw, raw),
            "workout": workout,
            "notes": _notes_text(_first(raw, LEGACY_KEYS["notes"])),
            "mode": _text(_first(raw, LEGACY_KEYS["mode"])),
            "event_name": _text(_first(raw, LEGACY_KEYS["event_name"])),
            "nutrition_totals": nutrition_totals,
            "_provided_sections": sorted(provided_sections),
        },
        warnings,
    )


def normalize_import_document(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        top_version = _text(payload.get("schema_version"))
        if top_version != IMPORT_SCHEMA_VERSION:
            raise ImportValidationError(
                [f"schema_version: 未対応です（{top_version or 'missing'}）。対応版は{IMPORT_SCHEMA_VERSION}です。"]
            )
        raw_records = payload["records"]
    elif isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, dict):
        raw_records = [payload]
    else:
        raise ImportValidationError(["JSONはobject、object配列、またはrecords配列を持つobjectにしてください。"])
    if not raw_records:
        raise ImportValidationError(["JSON配列が空です。1件以上のログが必要です。"])
    if not all(isinstance(record, dict) for record in raw_records):
        raise ImportValidationError(["各日次ログはobjectにしてください。"])

    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    for index, raw in enumerate(raw_records, start=1):
        try:
            record, record_warnings = _canonical_record(raw, index)
            records.append(record)
            warnings.extend(record_warnings)
        except ImportValidationError as exc:
            errors.extend(exc.errors)
            warnings.extend(exc.warnings)
    dates = [record["date"] for record in records]
    duplicates = sorted({date for date in dates if dates.count(date) > 1})
    if duplicates:
        errors.append(f"同じJSON内で日付が重複しています: {', '.join(duplicates)}")
    if errors:
        raise ImportValidationError(errors, warnings)
    return {
        "metadata": {
            "import_engine_version": IMPORT_ENGINE_VERSION,
            "schema_version": IMPORT_SCHEMA_VERSION,
        },
        "records": records,
        "warnings": warnings,
    }


def parse_import_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(text or ""))
    except json.JSONDecodeError as exc:
        raise ImportValidationError([f"JSON形式エラー: {exc.msg}（line {exc.lineno}, column {exc.colno}）"]) from exc
    return normalize_import_document(payload)


def workout_counts(workout: dict[str, Any] | None) -> dict[str, int]:
    workout = workout or {}
    exercises = workout.get("exercises") if isinstance(workout.get("exercises"), list) else []
    return {
        "session_count": 1 if workout.get("performed") else 0,
        "exercise_count": len(exercises),
        "set_count": sum(len(exercise.get("sets") or []) for exercise in exercises if isinstance(exercise, dict)),
    }


def meal_count(record: dict[str, Any]) -> int:
    return sum(len(record.get("meals", {}).get(meal_type) or []) for meal_type in MEAL_TYPES)


def import_fingerprint(record: dict[str, Any]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def import_document_fingerprint(document: dict[str, Any]) -> str:
    records = document.get("records") if isinstance(document, dict) else None
    encoded = json.dumps(records or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def new_import_id(record: dict[str, Any]) -> str:
    return f"imp_{record['date'].replace('-', '')}_{import_fingerprint(record)[:16]}"


def detect_anomalies(record: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    weight = record.get("weight")
    if weight is not None and not ANOMALY_THRESHOLDS["weight_min_kg"] <= weight <= ANOMALY_THRESHOLDS["weight_max_kg"]:
        add("weight_out_of_range", f"体重{weight:g}kgは確認推奨範囲外です。")
    sleep = (record.get("sleep") or {}).get("hours")
    if sleep is not None and sleep > ANOMALY_THRESHOLDS["sleep_max_hours"]:
        add("sleep_out_of_range", f"睡眠{sleep:g}時間は24時間を超えています。")
    steps = record.get("steps")
    if steps is not None and (steps < 0 or steps > ANOMALY_THRESHOLDS["steps_max"]):
        add("steps_out_of_range", f"歩数{steps:,}歩は確認推奨範囲外です。")
    condition = record.get("condition")
    if condition is not None and not ANOMALY_THRESHOLDS["condition_min"] <= condition <= ANOMALY_THRESHOLDS["condition_max"]:
        add("condition_out_of_range", f"体調{condition:g}は0から10の範囲外です。")
    total = (record.get("nutrition_totals") or {}).get("calories_kcal")
    if total is not None and total > ANOMALY_THRESHOLDS["calories_max_kcal"]:
        add("calories_out_of_range", f"摂取カロリー{total:g}kcalは確認推奨範囲外です。")
    names = [
        str(item.get("name") or "").strip().lower()
        for meal_type in MEAL_TYPES
        for item in record.get("meals", {}).get(meal_type) or []
    ]
    repeated = sorted({name for name in names if name and names.count(name) >= ANOMALY_THRESHOLDS["duplicate_food_count"]})
    if repeated:
        add("repeated_food", f"同一食品が大量に重複しています: {', '.join(repeated)}")
    return warnings


def preview_import(document: dict[str, Any], existing_dates: set[str] | None = None) -> dict[str, Any]:
    existing_dates = existing_dates or set()
    records = document.get("records") or []
    rows = []
    all_warnings = list(document.get("warnings") or [])
    for record in records:
        counts = workout_counts(record.get("workout"))
        anomalies = detect_anomalies(record)
        all_warnings.extend(item["message"] for item in anomalies)
        rows.append(
            {
                "date": record["date"],
                "weight": record.get("weight"),
                "sleep_hours": (record.get("sleep") or {}).get("hours"),
                "condition": record.get("condition"),
                "steps": record.get("steps"),
                "meal_items": meal_count(record),
                **counts,
                "duration_minutes": (record.get("workout") or {}).get("duration_minutes"),
                "conflict": record["date"] in existing_dates,
                "warning_count": len(anomalies),
            }
        )
    return {
        "records": rows,
        "record_count": len(rows),
        "meal_item_count": sum(row["meal_items"] for row in rows),
        "workout_session_count": sum(row["session_count"] for row in rows),
        "exercise_count": sum(row["exercise_count"] for row in rows),
        "set_count": sum(row["set_count"] for row in rows),
        "conflict_count": sum(1 for row in rows if row["conflict"]),
        "warnings": all_warnings,
    }


def _known_nutrition_from_resolution(resolution: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    items = resolution.get("items") or []
    if len(items) != 1:
        return None, None
    item = items[0]
    origin = item.get("selected_origin")
    if origin not in TRUSTED_RESOLUTION_ORIGINS:
        return None, origin
    nutrition = item.get("total_nutrition")
    return (deepcopy(nutrition) if isinstance(nutrition, dict) else None), origin


def resolve_record_nutrition(
    record: dict[str, Any],
    resolver: Callable[[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Resolve each food through exactly one path and retain unknown counts."""
    meal_results: dict[str, dict[str, Any]] = {}
    totals = {field: 0.0 for field in NUTRITION_FIELDS}
    known_by_field = {field: 0 for field in NUTRITION_FIELDS}
    unknown_calorie_count = 0

    for meal_type in MEAL_TYPES:
        resolved_items: list[dict[str, Any]] = []
        meal_totals = {field: 0.0 for field in NUTRITION_FIELDS}
        meal_known = {field: 0 for field in NUTRITION_FIELDS}
        for item in record.get("meals", {}).get(meal_type) or []:
            explicit = item.get("nutrition") if isinstance(item.get("nutrition"), dict) else None
            nutrition = None
            if explicit and any(explicit.get(field) is not None for field in NUTRITION_FIELDS):
                if explicit.get("basis") == "total":
                    nutrition = deepcopy(explicit)
                else:
                    quantity_result = calculate_lookup_total(
                        {"matched": True, "nutrition": explicit},
                        item.get("quantity"),
                        item.get("unit"),
                    )
                    if not quantity_result.get("needs_review"):
                        nutrition = deepcopy(quantity_result.get("total_nutrition"))
            source = "explicit" if nutrition is not None else None
            if nutrition is None:
                resolution = resolver(str(item.get("name") or ""), meal_type)
                nutrition, origin = _known_nutrition_from_resolution(resolution)
                source = origin if nutrition is not None else None
            result = deepcopy(item)
            result["resolved_nutrition"] = nutrition
            result["calorie_source"] = source
            result["needs_review"] = nutrition is None or nutrition.get("calories_kcal") is None
            if result["needs_review"]:
                unknown_calorie_count += 1
            for field in NUTRITION_FIELDS:
                value = _number((nutrition or {}).get(field))
                if value is not None:
                    meal_totals[field] += value
                    totals[field] += value
                    meal_known[field] += 1
                    known_by_field[field] += 1
            resolved_items.append(result)
        meal_results[meal_type] = {
            "items": resolved_items,
            "totals": {
                field: round(value, 2) if meal_known[field] else None
                for field, value in meal_totals.items()
            },
        }

    explicit_daily = record.get("nutrition_totals") or {}
    final_totals: dict[str, Any] = {}
    total_sources: dict[str, str] = {}
    for field in NUTRITION_FIELDS:
        explicit_value = _number(explicit_daily.get(field))
        if explicit_value is not None:
            final_totals[field] = explicit_value
            total_sources[field] = "explicit_daily"
        elif known_by_field[field]:
            final_totals[field] = round(totals[field], 2)
            total_sources[field] = "resolved_items"
        else:
            final_totals[field] = None
            total_sources[field] = "unknown"

    return {
        "meals": meal_results,
        "totals": final_totals,
        "total_sources": total_sources,
        "unknown_calorie_count": unknown_calorie_count,
    }


def workout_summary_text(workout: dict[str, Any] | None) -> str:
    workout = workout or {}
    if not workout.get("performed"):
        return ""
    segments = []
    if workout.get("program_name"):
        segments.append(str(workout["program_name"]))
    for exercise in workout.get("exercises") or []:
        sets = exercise.get("sets") or []
        set_parts = []
        for item in sets:
            weight = item.get("weight_kg")
            reps = item.get("reps")
            if weight is not None and reps is not None:
                set_parts.append(f"{weight:g}kg×{reps}")
            elif reps is not None:
                set_parts.append(f"{reps}回")
        segments.append(f"{exercise.get('name', '')} {' / '.join(set_parts)}".strip())
    return " / ".join(segment for segment in segments if segment)


def meal_display_text(items: list[dict[str, Any]]) -> str:
    return "、".join(str(item.get("name") or "") for item in items if item.get("name"))


def canonical_to_projection(
    record: dict[str, Any],
    nutrition: dict[str, Any],
) -> dict[str, Any]:
    workout = record.get("workout") or {}
    counts = workout_counts(workout)
    alcohol = record.get("alcohol") or {}
    meals = nutrition.get("meals") or {}
    calorie_columns = {
        "breakfast": "朝カロリー(kcal)",
        "lunch": "昼カロリー(kcal)",
        "dinner": "夜カロリー(kcal)",
        "snacks": "間食カロリー(kcal)",
        "drinks": "ドリンクカロリー(kcal)",
    }
    row: dict[str, Any] = {
        "日付": record["date"],
        "体重": record.get("weight"),
        "歩数": record.get("steps"),
        "睡眠時間": (record.get("sleep") or {}).get("hours"),
        "体調": record.get("condition"),
        "モード": record.get("mode") or "NORMAL",
        "イベント名": record.get("event_name") or "",
        "コメント": record.get("notes") or "",
        "飲酒": "あり" if alcohol.get("consumed") is True else "なし" if alcohol.get("consumed") is False else "",
        "飲酒内容": alcohol.get("detail") or "",
        "飲酒レベル": alcohol.get("level") or "",
        "筋トレ有無": "あり" if workout.get("performed") else "なし",
        "筋トレ内容": workout_summary_text(workout),
        "筋トレセッション数": counts["session_count"],
        "筋トレ種目数": counts["exercise_count"],
        "筋トレセット数": counts["set_count"],
        "筋トレ時間(分)": workout.get("duration_minutes"),
        "構造化筋トレJSON": json.dumps(workout, ensure_ascii=False, separators=(",", ":")),
        "構造化食事JSON": json.dumps(meals, ensure_ascii=False, separators=(",", ":")),
        "Import ID": new_import_id(record),
        "Import Schema Version": record["schema_version"],
        "カロリー不明件数": nutrition.get("unknown_calorie_count", 0),
        "推定摂取カロリー": nutrition.get("totals", {}).get("calories_kcal"),
        "タンパク質(g)": nutrition.get("totals", {}).get("protein_g"),
        "脂質(g)": nutrition.get("totals", {}).get("fat_g"),
        "炭水化物(g)": nutrition.get("totals", {}).get("carbs_g"),
    }
    for meal_type, label in MEAL_LABELS.items():
        row[label] = meal_display_text(record.get("meals", {}).get(meal_type) or [])
        row[calorie_columns[meal_type]] = (meals.get(meal_type) or {}).get("totals", {}).get("calories_kcal")
    return row


def export_projection(row: dict[str, Any]) -> dict[str, Any]:
    def decode(column: str, default: Any) -> Any:
        value = row.get(column)
        if isinstance(value, (dict, list)):
            return deepcopy(value)
        try:
            return json.loads(str(value)) if value not in (None, "") else deepcopy(default)
        except (TypeError, json.JSONDecodeError):
            return deepcopy(default)

    structured_meals = decode("構造化食事JSON", {})
    if structured_meals and all(
        isinstance(value, dict) and "items" in value for value in structured_meals.values()
    ):
        meals = {meal_type: deepcopy((structured_meals.get(meal_type) or {}).get("items") or []) for meal_type in MEAL_TYPES}
        for items in meals.values():
            for item in items:
                if "resolved_nutrition" in item and not item.get("nutrition"):
                    item["nutrition"] = deepcopy(item["resolved_nutrition"])
                for extra in ("resolved_nutrition", "calorie_source", "needs_review"):
                    item.pop(extra, None)
    else:
        meals = {
            meal_type: _meal_items(row.get(label), f"export.meals.{meal_type}", [], [])
            for meal_type, label in MEAL_LABELS.items()
        }
    workout = decode("構造化筋トレJSON", None)
    if not isinstance(workout, dict):
        workout = _workout(row.get("筋トレ内容") if str(row.get("筋トレ有無") or "") == "あり" else None, [], [])
    totals = {
        "calories_kcal": _number(row.get("推定摂取カロリー")),
        "protein_g": _number(row.get("タンパク質(g)")),
        "fat_g": _number(row.get("脂質(g)")),
        "carbs_g": _number(row.get("炭水化物(g)")),
        "basis": "total",
    }
    return {
        "schema_version": IMPORT_SCHEMA_VERSION,
        "date": _date(row.get("日付")),
        "weight": _number(row.get("体重")) or None,
        "sleep": {"hours": _number(row.get("睡眠時間"))},
        "condition": _number(row.get("体調")),
        "steps": _integer(row.get("歩数")),
        "meals": meals,
        "alcohol": {
            "consumed": True if str(row.get("飲酒") or "") == "あり" else False if str(row.get("飲酒") or "") == "なし" else None,
            "detail": _text(row.get("飲酒内容")),
            "level": _text(row.get("飲酒レベル")),
        },
        "workout": workout,
        "notes": _text(row.get("コメント")),
        "mode": _text(row.get("モード")),
        "event_name": _text(row.get("イベント名")),
        "nutrition_totals": totals,
    }


def structured_import_log(
    *,
    import_id: str,
    user_id: str,
    records: list[dict[str, Any]],
    warning_count: int,
    section: str,
    started_at: float,
    error_location: str | None = None,
) -> dict[str, Any]:
    return {
        "event": "bodyos_import",
        "import_id": import_id,
        "user_id": user_id,
        "dates": [record.get("date") for record in records],
        "schema_version": IMPORT_SCHEMA_VERSION,
        "section": section,
        "warning_count": int(warning_count),
        "error_location": error_location,
        "duration_ms": round((time.monotonic() - started_at) * 1000, 1),
    }


def operation_import_id() -> str:
    return f"import_{uuid4().hex}"


__all__ = [
    "ANOMALY_THRESHOLDS",
    "IMPORT_ENGINE_VERSION",
    "IMPORT_SCHEMA_VERSION",
    "ImportValidationError",
    "MEAL_LABELS",
    "MEAL_TYPES",
    "canonical_to_projection",
    "detect_anomalies",
    "export_projection",
    "import_document_fingerprint",
    "import_fingerprint",
    "meal_count",
    "new_import_id",
    "normalize_import_document",
    "operation_import_id",
    "parse_import_json",
    "preview_import",
    "resolve_record_nutrition",
    "structured_import_log",
    "workout_counts",
    "workout_summary_text",
]
