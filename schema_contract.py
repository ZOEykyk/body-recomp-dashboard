from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "bodyos-daily-log.schema.json"
CANONICAL_EXAMPLE_PATH = Path(__file__).resolve().parent / "tests" / "fixtures" / "schema_1_0_canonical_example.json"
BASIS_VALUES = ("per_item", "per_package", "per_serving", "per_100g", "per_100ml", "total", "unknown", None)

KEY_SUGGESTIONS = {
    "nutrition": "nutrition_totals",
    "condition_score": "condition",
    "sleep_hours": "sleep.hours",
    "calories": "calories_kcal",
    "protein": "protein_g",
    "fat": "fat_g",
    "carbs": "carbs_g",
    "carbohydrates_g": "carbs_g",
    "sessions": "workout.exercises",
    "type": "set_type",
    "snack": "snacks",
}
AMBIGUOUS_TOP_LEVEL_KEYS = {"summary", "memo", "nutrition_summary", "training", "exercise"}


@lru_cache(maxsize=1)
def load_daily_log_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def schema_validator() -> Draft202012Validator:
    return Draft202012Validator(load_daily_log_schema(), format_checker=FormatChecker())


def load_canonical_example() -> dict[str, Any]:
    return json.loads(CANONICAL_EXAMPLE_PATH.read_text(encoding="utf-8"))


def json_path(parts: list[Any] | tuple[Any, ...]) -> str:
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += ("." if path else "") + str(part)
    return path or "$"


def _change(source: str, target: str, *, action: str = "renamed") -> dict[str, Any]:
    return {
        "source_path": source,
        "target_path": target,
        "action": action,
        "message": f"{source} → {target}",
    }


def _issue(
    path: str,
    message: str,
    *,
    suggestion: str | None = None,
    auto_fixable: bool = False,
    code: str = "schema_validation",
) -> dict[str, Any]:
    return {
        "path": path or "$",
        "message": message,
        "suggestion": suggestion,
        "auto_fixable": bool(auto_fixable),
        "code": code,
    }


def format_issue(issue: dict[str, Any]) -> str:
    text = f"{issue['path']}: {issue['message']}"
    if issue.get("suggestion"):
        text += f" 修正候補: {issue['suggestion']}"
    text += f" 自動修正: {'可' if issue.get('auto_fixable') else '不可'}"
    return text


def _same_value(left: Any, right: Any) -> bool:
    return left == right


def _move_alias(
    mapping: dict[str, Any],
    alias: str,
    canonical: str,
    path: str,
    changes: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    *,
    transform: Callable[[Any], Any] | None = None,
    equivalent: Callable[[Any, Any], bool] = _same_value,
) -> None:
    if alias not in mapping:
        return
    source_path = f"{path}.{alias}" if path else alias
    target_path = f"{path}.{canonical}" if path else canonical
    alias_value = transform(mapping[alias]) if transform else deepcopy(mapping[alias])
    if canonical in mapping:
        if equivalent(mapping[canonical], alias_value):
            mapping.pop(alias)
            changes.append(_change(source_path, target_path, action="removed_redundant_alias"))
            return
        issues.append(
            _issue(
                source_path,
                f"`{canonical}` と `{alias}` が同時に存在し、値が一致しません。",
                suggestion=f"どちらを採用するか決め、`{canonical}` だけを残してください。",
                code="alias_conflict",
            )
        )
        return
    mapping[canonical] = alias_value
    mapping.pop(alias)
    changes.append(_change(source_path, target_path))


def _normalize_quantity(
    item: dict[str, Any],
    path: str,
    changes: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    quantity = item.get("quantity")
    if isinstance(quantity, str):
        if "quantity_text" in item and item["quantity_text"] != quantity:
            issues.append(
                _issue(
                    f"{path}.quantity",
                    "`quantity` の自由記述と `quantity_text` が一致しません。",
                    suggestion="原文を `quantity_text` に一つだけ残してください。",
                    code="alias_conflict",
                )
            )
            return
        item["quantity"] = None
        item["quantity_text"] = quantity
        changes.append(_change(f"{path}.quantity", f"{path}.quantity_text", action="preserved_quantity_text"))
        return
    if not isinstance(quantity, dict):
        return
    unknown = sorted(set(quantity) - {"value", "unit"})
    if unknown:
        return
    value = quantity.get("value")
    nested_unit = quantity.get("unit")
    if nested_unit is not None and "unit" in item and item["unit"] != nested_unit:
        issues.append(
            _issue(
                f"{path}.quantity.unit",
                "`unit` と `quantity.unit` が同時に存在し、値が一致しません。",
                suggestion="食品直下の `unit` に統一してください。",
                code="alias_conflict",
            )
        )
        return
    item["quantity"] = value
    if nested_unit is not None:
        item["unit"] = nested_unit
    changes.append(_change(f"{path}.quantity", f"{path}.quantity / {path}.unit", action="expanded_quantity"))


def _normalize_nutrition_aliases(
    nutrition: dict[str, Any],
    path: str,
    changes: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    for alias, canonical in (
        ("calories", "calories_kcal"),
        ("protein", "protein_g"),
        ("fat", "fat_g"),
        ("carbs", "carbs_g"),
        ("carbohydrates_g", "carbs_g"),
    ):
        _move_alias(nutrition, alias, canonical, path, changes, issues)


def _normalize_direct_item_nutrition(
    item: dict[str, Any],
    path: str,
    changes: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    direct_keys = ("calories_kcal", "protein_g", "fat_g", "carbs_g", "carbohydrates_g")
    present = [key for key in direct_keys if key in item]
    has_basis = "basis" in item or "nutrition_basis" in item
    if not present and not has_basis:
        return
    direct: dict[str, Any] = {}
    for key in present:
        canonical = "carbs_g" if key == "carbohydrates_g" else key
        if canonical in direct and direct[canonical] != item[key]:
            issues.append(
                _issue(
                    f"{path}.{key}",
                    f"`{canonical}` と `{key}` の値が一致しません。",
                    suggestion=f"`nutrition.{canonical}` に値を一つだけ指定してください。",
                    code="alias_conflict",
                )
            )
            continue
        direct[canonical] = deepcopy(item[key])
    basis = item.get("nutrition_basis", item.get("basis", "total"))
    direct["basis"] = basis
    nested = item.get("nutrition")
    if nested is not None:
        if not isinstance(nested, dict) or any(nested.get(key) != value for key, value in direct.items()):
            issues.append(
                _issue(
                    f"{path}.nutrition",
                    "nested `nutrition` と食品直下の栄養値が同時に存在し、一致しません。",
                    suggestion="nested `nutrition` だけに統一してください。",
                    code="alias_conflict",
                )
            )
            return
        action = "removed_redundant_alias"
    else:
        item["nutrition"] = direct
        action = "nested_item_nutrition"
    for key in present:
        item.pop(key, None)
        changes.append(_change(f"{path}.{key}", f"{path}.nutrition.{('carbs_g' if key == 'carbohydrates_g' else key)}", action=action))
    for key in ("basis", "nutrition_basis"):
        if key in item:
            item.pop(key)
            changes.append(_change(f"{path}.{key}", f"{path}.nutrition.basis", action=action))


def _normalize_meals(
    record: dict[str, Any],
    path: str,
    changes: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    meals = record.get("meals")
    if not isinstance(meals, dict):
        return
    meals_path = f"{path}.meals" if path else "meals"
    _move_alias(meals, "snack", "snacks", meals_path, changes, issues)
    for meal_type in ("breakfast", "lunch", "dinner", "snacks", "drinks"):
        items = meals.get(meal_type)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            item_path = f"{meals_path}.{meal_type}[{index}]"
            _normalize_quantity(item, item_path, changes, issues)
            nutrition = item.get("nutrition")
            if isinstance(nutrition, dict):
                _normalize_nutrition_aliases(nutrition, f"{item_path}.nutrition", changes, issues)
            _normalize_direct_item_nutrition(item, item_path, changes, issues)


def _normalize_workout(
    record: dict[str, Any],
    path: str,
    changes: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    workout = record.get("workout")
    if not isinstance(workout, dict):
        return
    workout_path = f"{path}.workout" if path else "workout"
    if "sessions" in workout:
        sessions = workout.get("sessions")
        safe_session = (
            isinstance(sessions, list)
            and len(sessions) == 1
            and isinstance(sessions[0], dict)
            and set(sessions[0]) == {"exercises"}
            and "exercises" not in workout
        )
        if safe_session:
            workout["exercises"] = deepcopy(sessions[0]["exercises"])
            workout.pop("sessions")
            changes.append(_change(f"{workout_path}.sessions[0].exercises", f"{workout_path}.exercises", action="flattened_single_session"))
        else:
            issues.append(
                _issue(
                    f"{workout_path}.sessions",
                    "`workout.sessions` は単一sessionで情報損失なく変換できる場合のみ互換対象です。",
                    suggestion="単一sessionの種目を `workout.exercises` へ移し、`sessions` を削除してください。",
                    code="unsafe_workout_sessions",
                )
            )
    exercises = workout.get("exercises")
    if not isinstance(exercises, list):
        return
    for exercise_index, exercise in enumerate(exercises):
        if not isinstance(exercise, dict) or not isinstance(exercise.get("sets"), list):
            continue
        for set_index, workout_set in enumerate(exercise["sets"]):
            if not isinstance(workout_set, dict):
                continue
            set_path = f"{workout_path}.exercises[{exercise_index}].sets[{set_index}]"
            _move_alias(workout_set, "type", "set_type", set_path, changes, issues)


def normalize_compatibility_record(
    record: dict[str, Any],
    *,
    path: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = deepcopy(record)
    changes: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    _move_alias(normalized, "nutrition", "nutrition_totals", path, changes, issues)
    _move_alias(normalized, "condition_score", "condition", path, changes, issues)
    _move_alias(
        normalized,
        "sleep_hours",
        "sleep",
        path,
        changes,
        issues,
        transform=lambda value: {"hours": value},
        equivalent=lambda canonical, alias: canonical == alias or (
            isinstance(canonical, (int, float)) and canonical == alias.get("hours")
        ),
    )
    if isinstance(normalized.get("sleep"), (int, float)) and not isinstance(normalized.get("sleep"), bool):
        sleep_path = f"{path}.sleep" if path else "sleep"
        normalized["sleep"] = {"hours": normalized["sleep"]}
        changes.append(_change(sleep_path, f"{sleep_path}.hours", action="expanded_sleep"))
    if isinstance(normalized.get("notes"), list):
        notes_path = f"{path}.notes" if path else "notes"
        normalized["notes"] = "\n".join(str(item).strip() for item in normalized["notes"] if str(item).strip()) or None
        changes.append(_change(notes_path, notes_path, action="joined_notes_array"))
    _normalize_meals(normalized, path, changes, issues)
    _normalize_workout(normalized, path, changes, issues)
    return normalized, changes, issues


def _additional_property_names(message: str) -> list[str]:
    return re.findall(r"'([^']+)'", message)


def _schema_error_issues(record: dict[str, Any], *, prefix: str = "") -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for error in sorted(schema_validator().iter_errors(record), key=lambda item: list(item.absolute_path)):
        parts = list(error.absolute_path)
        base_path = json_path(parts)
        if prefix:
            base_path = prefix if base_path == "$" else f"{prefix}.{base_path}"
        if error.validator == "additionalProperties":
            unknown_keys = _additional_property_names(error.message) or ["unknown"]
            for key in unknown_keys:
                path = f"{base_path}.{key}" if base_path != "$" else key
                suggestion = KEY_SUGGESTIONS.get(key)
                issues.append(
                    _issue(
                        path,
                        "未定義フィールドです。",
                        suggestion=(f"`{suggestion}` を使用してください。" if suggestion else "Schema 1.0に存在する正式keyだけを使用してください。"),
                        auto_fixable=False,
                        code="additional_property",
                    )
                )
            continue
        if error.validator == "required":
            missing = _additional_property_names(error.message)
            key = missing[0] if missing else "required field"
            path = f"{base_path}.{key}" if base_path != "$" else key
            issues.append(_issue(path, "必須フィールドがありません。", suggestion=f"`{key}` を追加してください。"))
            continue
        if error.validator == "enum":
            allowed = ", ".join("null" if value is None else str(value) for value in error.validator_value)
            issues.append(
                _issue(
                    base_path,
                    f"`{error.instance}` は許可されていません。",
                    suggestion=f"許容値: {allowed}",
                    code="invalid_enum",
                )
            )
            continue
        message = {
            "const": f"Schema versionは `{error.validator_value}` にしてください。",
            "format": "YYYY-MM-DD形式の日付にしてください。",
            "type": f"値の型が不正です。許容型: {error.validator_value}",
            "minimum": f"{error.validator_value}以上の値にしてください。",
            "exclusiveMinimum": f"{error.validator_value}より大きい値にしてください。",
            "maximum": f"{error.validator_value}以下の値にしてください。",
        }.get(error.validator, error.message)
        issues.append(_issue(base_path, message, code=f"schema_{error.validator}"))
    return issues


def validate_schema_record(record: dict[str, Any], *, prefix: str = "") -> list[dict[str, Any]]:
    return _schema_error_issues(record, prefix=prefix)


def canonical_record_for_json(record: dict[str, Any]) -> dict[str, Any]:
    canonical = deepcopy(record)
    canonical.pop("_provided_sections", None)
    workout = canonical.get("workout")
    if isinstance(workout, dict):
        for exercise in workout.get("exercises") or []:
            if not isinstance(exercise, dict):
                continue
            exercise.pop("exercise_order", None)
            for workout_set in exercise.get("sets") or []:
                if isinstance(workout_set, dict):
                    workout_set.pop("set_order", None)
    return canonical


def canonical_document_payload(document: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    records = [canonical_record_for_json(record) for record in document.get("records") or []]
    if len(records) == 1:
        return records[0]
    return {"schema_version": SCHEMA_VERSION, "records": records}


def deduplicate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (str(issue.get("path")), str(issue.get("code")), str(issue.get("message")))
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


__all__ = [
    "AMBIGUOUS_TOP_LEVEL_KEYS",
    "BASIS_VALUES",
    "CANONICAL_EXAMPLE_PATH",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
    "canonical_document_payload",
    "canonical_record_for_json",
    "deduplicate_issues",
    "format_issue",
    "json_path",
    "load_canonical_example",
    "load_daily_log_schema",
    "normalize_compatibility_record",
    "validate_schema_record",
]
