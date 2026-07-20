from __future__ import annotations

import datetime as dt
import base64
import json
import logging
import os
import re
from io import StringIO
from pathlib import Path
from typing import Any
from urllib import error, request

import pandas as pd
import streamlit as st

from bodyos_standard import (
    MODES,
    SCORE_COMPONENTS,
    calculate_bodyos_score,
    normalize_mode,
)
from data_integrity import (
    parse_optional_positive_number,
    valid_weight_series,
)
from dashboard import render_dashboard
from food_master_repository import JsonFoodMasterRepository
from food_repository_factory import create_food_master_repository
from food_master_models import meal_content_fingerprint
from food_master_ui import render_food_master_management
from food_knowledge_dashboard import render_food_knowledge_dashboard
from food_parser import parse_food_text
from food_resolver import RESOLUTION_ORIGINS, build_food_knowledge_snapshot, resolve_food_text
from personal_food_master import remember_food_encounters_with_summary

DATA_FILE = "records.csv"
TARGET_WEIGHT = 76.0
DEFAULT_GITHUB_REPOSITORY = "ZOEykyk/body-recomp-dashboard"
DEFAULT_RECORDS_BRANCH = "main"
DEFAULT_PERSONAL_FOOD_USER_ID = "local-default"
PERSONAL_FOOD_MASTER_FILE = "personal_food_master.json"
FOOD_ENCOUNTERS_FILE = "food_encounters.jsonl"
BODY_SCORE_COLUMNS = ["Body Score"] + SCORE_COMPONENTS

REQUIRED_COLUMNS = [
    "日付",
    "モード",
    "イベント名",
    "体重",
    "歩数",
    "歩数ランク",
    "睡眠時間",
    "朝",
    "昼",
    "夜",
    "間食",
    "仕事中のドリンク",
    "推定摂取カロリー",
    "筋トレ有無",
    "筋トレ内容",
    "体調",
    "飲酒",
    "飲酒内容",
    "飲酒レベル",
    "今日の採点",
    "コメント",
]

OPTIONAL_COLUMNS = [
    "朝カロリー(kcal)",
    "昼カロリー(kcal)",
    "夜カロリー(kcal)",
    "間食カロリー(kcal)",
    "ドリンクカロリー(kcal)",
    "ベンチプレス(kg)",
    "カロリー推定信頼度",
    "Body Score",
    "手動Body Score",
    "Body Score種別",
    "体重スコア",
    "食事スコア",
    "タンパク質スコア",
    "歩数スコア",
    "筋トレスコア",
    "睡眠スコア",
    "体調スコア",
    "飲酒スコア",
]

COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

COLUMN_ALIASES = {
    "mode": "モード",
    "event": "イベント名",
    "event_name": "イベント名",
    "body_score": "Body Score",
    "total_score": "Body Score",
    "体重(kg)": "体重",
    "推定摂取カロリー(kcal)": "推定摂取カロリー",
    "摂取カロリー": "推定摂取カロリー",
    "筋トレ": "筋トレ有無",
    "トレーニング": "筋トレ有無",
    "ドリンク": "仕事中のドリンク",
    "仕事中ドリンク": "仕事中のドリンク",
}

TEXT_COLUMNS = [
    "モード",
    "イベント名",
    "歩数ランク",
    "朝",
    "昼",
    "夜",
    "間食",
    "仕事中のドリンク",
    "筋トレ有無",
    "筋トレ内容",
    "体調",
    "飲酒",
    "飲酒内容",
    "飲酒レベル",
    "Body Score種別",
    "コメント",
    "カロリー推定信頼度",
]

NUMERIC_COLUMNS = [
    "体重",
    "歩数",
    "睡眠時間",
    "推定摂取カロリー",
    "今日の採点",
    "朝カロリー(kcal)",
    "昼カロリー(kcal)",
    "夜カロリー(kcal)",
    "間食カロリー(kcal)",
    "ドリンクカロリー(kcal)",
    "ベンチプレス(kg)",
    "Body Score",
    "手動Body Score",
    "体重スコア",
    "食事スコア",
    "タンパク質スコア",
    "歩数スコア",
    "筋トレスコア",
    "睡眠スコア",
    "体調スコア",
    "飲酒スコア",
]

CALORIE_CONFIDENCE_LEVELS = {"low": 0, "medium": 1, "high": 2}

LOGGER = logging.getLogger(__name__)

JSON_KEY_ALIASES = {
    "日付": ["日付", "date", "record_date", "記録日"],
    "モード": ["モード", "mode"],
    "イベント名": ["イベント名", "event", "event_name"],
    "体重": ["体重", "体重(kg)", "weight", "weight_kg"],
    "歩数": ["歩数", "steps"],
    "歩数ランク": ["歩数ランク", "step_rank", "steps_rank"],
    "睡眠時間": ["睡眠時間", "睡眠", "sleep", "sleep_hours"],
    "朝": ["朝", "朝食", "breakfast"],
    "昼": ["昼", "昼食", "lunch"],
    "夜": ["夜", "夕食", "晩ごはん", "dinner", "meal"],
    "間食": ["間食", "snack", "snacks"],
    "仕事中のドリンク": ["仕事中のドリンク", "ドリンク", "work_drinks", "drinks"],
    "推定摂取カロリー": [
        "推定摂取カロリー",
        "推定摂取カロリー(kcal)",
        "摂取カロリー",
        "total_kcal",
        "calories",
        "kcal",
    ],
    "筋トレ有無": ["筋トレ有無", "筋トレ", "trained", "performed", "workout.performed"],
    "筋トレ内容": ["筋トレ内容", "筋トレメニュー", "training_detail", "workout_detail", "menu", "workout.menu"],
    "体調": ["体調", "condition", "health"],
    "飲酒": ["飲酒", "alcohol", "drinking", "drank_alcohol"],
    "飲酒内容": ["飲酒内容", "alcohol_detail"],
    "飲酒レベル": ["飲酒レベル", "alcohol_level", "drinking_level"],
    "今日の採点": ["今日の採点", "採点", "score"],
    "Body Score": ["Body Score", "body_score", "total_score"],
    "体重スコア": ["体重スコア"],
    "食事スコア": ["食事スコア"],
    "タンパク質スコア": ["タンパク質スコア"],
    "歩数スコア": ["歩数スコア"],
    "筋トレスコア": ["筋トレスコア"],
    "睡眠スコア": ["睡眠スコア"],
    "体調スコア": ["体調スコア"],
    "飲酒スコア": ["飲酒スコア"],
    "コメント": ["コメント", "comment", "memo", "メモ"],
}

st.set_page_config(page_title="ボディリコンプ管理システム", page_icon="🏋️", layout="wide")
st.title("🏋️ ボディリコンプ管理システム")
st.caption("食事・体重・歩数・筋トレをCSVに保存し、減量ペースを分析します。")


class RecordValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def get_config_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default) or "").strip()


def food_repository_config() -> dict[str, str]:
    names = [
        "FOOD_KNOWLEDGE_REPOSITORY",
        "FOOD_KNOWLEDGE_MODE",
        "FOOD_KNOWLEDGE_USER_ID",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_TIMEOUT_SECONDS",
    ]
    return {name: get_config_value(name) for name in names}


PERSONAL_FOOD_USER_ID = get_config_value("FOOD_KNOWLEDGE_USER_ID", DEFAULT_PERSONAL_FOOD_USER_ID)
LOCAL_FOOD_REPOSITORY = JsonFoodMasterRepository(
    Path(__file__).with_name(PERSONAL_FOOD_MASTER_FILE),
    Path(__file__).with_name(FOOD_ENCOUNTERS_FILE),
)
PERSONAL_FOOD_REPOSITORY = create_food_master_repository(food_repository_config(), LOCAL_FOOD_REPOSITORY)


def github_storage_config() -> dict[str, str]:
    return {
        "token": get_config_value("GITHUB_TOKEN"),
        "repository": get_config_value("GITHUB_REPOSITORY", DEFAULT_GITHUB_REPOSITORY),
        "branch": get_config_value("RECORDS_CSV_BRANCH", DEFAULT_RECORDS_BRANCH),
        "path": get_config_value("RECORDS_CSV_PATH", DATA_FILE),
    }


def github_storage_enabled() -> bool:
    config = github_storage_config()
    return bool(config["token"] and config["repository"])


def github_request(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    config = github_storage_config()
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {config['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "body-recomp-dashboard",
        },
    )

    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            raise FileNotFoundError(detail) from exc
        raise RuntimeError(f"GitHub API error {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"GitHub APIに接続できませんでした: {exc.reason}") from exc


def github_file_url() -> str:
    config = github_storage_config()
    path = config["path"].replace("\\", "/")
    return f"https://api.github.com/repos/{config['repository']}/contents/{path}"


def read_github_records() -> tuple[str | None, str | None]:
    config = github_storage_config()
    url = f"{github_file_url()}?ref={config['branch']}"
    try:
        response = github_request("GET", url)
    except FileNotFoundError:
        return None, None

    content = base64.b64decode(response["content"]).decode("utf-8-sig")
    return content, response["sha"]


def write_github_records(csv_text: str) -> None:
    config = github_storage_config()
    _, sha = read_github_records()
    payload: dict[str, Any] = {
        "message": "Update records.csv from Streamlit app",
        "content": base64.b64encode(csv_text.encode("utf-8-sig")).decode("ascii"),
        "branch": config["branch"],
    }
    if sha:
        payload["sha"] = sha
    github_request("PUT", github_file_url(), payload)


def current_food_knowledge() -> dict[str, Any]:
    try:
        repository_snapshot = PERSONAL_FOOD_REPOSITORY.build_snapshot(PERSONAL_FOOD_USER_ID)
    except Exception as exc:
        LOGGER.warning("Food Knowledge read failed: %s", type(exc).__name__)
        repository_snapshot = {"personal_foods": []}
    return build_food_knowledge_snapshot(repository_snapshot["personal_foods"])


def estimate_calorie_detail(
    text: str,
    meal_type: str = "",
    *,
    knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility projection of the shared Food Resolver result."""
    resolution = resolve_food_text(
        str(text or ""),
        meal_type,
        knowledge=knowledge if knowledge is not None else current_food_knowledge(),
    )
    return {
        "kcal": resolution["kcal"],
        "confidence": resolution["confidence"],
        "detected_foods": resolution["detected_foods"],
        "unknown_items": resolution["unknown_items"],
        "parsed_foods": resolution["parsed_foods"],
        "nutrition_source_decisions": resolution["nutrition_source_decisions"],
        "resolution_counts": resolution["resolution_counts"],
        "food_resolution": resolution,
    }


def remember_saved_meals(
    meals: list[tuple[str, str, dict[str, Any]]],
    *,
    record_date: str,
    operation_id: str,
    used_at: str,
) -> dict[str, int]:
    """Persist Personal Food Master encounters only for newly saved/imported records."""
    summary = {
        "encounter_count": 0,
        "encounter_saved": 0,
        "duplicate_skipped": 0,
        "save_failed": 0,
        **{origin: 0 for origin in RESOLUTION_ORIGINS},
    }
    for meal_type, text, detail in meals:
        if not str(text or "").strip():
            continue
        content_operation_id = f"{operation_id}:content:{meal_content_fingerprint(text)}"
        parsed_foods = detail.get("parsed_foods") if isinstance(detail, dict) else None
        if not isinstance(parsed_foods, dict):
            parsed_foods = parse_food_text(str(text), meal_type)
        resolution = detail.get("food_resolution") if isinstance(detail, dict) else None
        if not isinstance(resolution, dict):
            resolution = resolve_food_text(str(text), meal_type, knowledge=current_food_knowledge())
        for origin in RESOLUTION_ORIGINS:
            summary[origin] += int((resolution.get("resolution_counts") or {}).get(origin, 0))
        persistence = remember_food_encounters_with_summary(
            PERSONAL_FOOD_REPOSITORY,
            PERSONAL_FOOD_USER_ID,
            parsed_foods,
            meal_type=meal_type,
            record_date=record_date,
            operation_id=content_operation_id,
            used_at=used_at,
            resolution=resolution,
        )
        summary["encounter_count"] += int(persistence["saved"])
        summary["encounter_saved"] += int(persistence["saved"])
        summary["duplicate_skipped"] += int(persistence["duplicates"])
        summary["save_failed"] += int(persistence["failed"])
    return summary


def empty_food_resolution_summary() -> dict[str, int]:
    return {
        "encounter_count": 0,
        "encounter_saved": 0,
        "duplicate_skipped": 0,
        "save_failed": 0,
        **{origin: 0 for origin in RESOLUTION_ORIGINS},
    }


def merge_food_resolution_summary(target: dict[str, int], source: dict[str, int]) -> None:
    for key in target:
        target[key] += int(source.get(key, 0))


def render_food_import_summary(summary: dict[str, int]) -> None:
    st.markdown("**Food Resolution Summary**")
    st.write(
        f"Food Master: {summary.get('personal', 0)}件 / "
        f"Official: {summary.get('official', 0)}件 / "
        f"Generic: {summary.get('generic', 0)}件 / "
        f"Fallback: {summary.get('fallback', 0)}件"
    )
    if summary.get("explicit", 0):
        st.caption(f"Explicit Nutrition: {summary['explicit']}件")
    st.caption(
        f"Encounter saved: {summary.get('encounter_saved', summary.get('encounter_count', 0))}件 / "
        f"Duplicate skipped: {summary.get('duplicate_skipped', 0)}件 / "
        f"Save failed: {summary.get('save_failed', 0)}件"
    )
    if summary.get("save_failed", 0):
        st.warning("一部のFood Encounterを保存できませんでした。records.csvの保存結果には影響ありません。")


def estimate_calories(text: str, meal_type: str = "") -> int:
    return int(estimate_calorie_detail(text, meal_type)["kcal"])


def final_kcal(auto_kcal: int, manual_kcal: int) -> int:
    return manual_kcal if manual_kcal > 0 else auto_kcal


def final_confidence(auto_confidence: str, manual_kcal: int) -> str:
    return "high" if manual_kcal > 0 else auto_confidence


def combine_calorie_confidence(*confidences: str) -> str:
    active = [confidence for confidence in confidences if confidence in CALORIE_CONFIDENCE_LEVELS]
    if not active:
        return "low"
    return min(active, key=lambda confidence: CALORIE_CONFIDENCE_LEVELS[confidence])


def calorie_confidence_for_entered_meals(*meal_details: tuple[Any, dict[str, Any]]) -> str:
    confidences = [
        str(detail["confidence"])
        for text, detail in meal_details
        if text is not None and str(text).strip()
    ]
    return combine_calorie_confidence(*confidences)


def rank_steps(steps: Any) -> str:
    value = parse_number(steps, default=0)
    if value >= 12000:
        return "S"
    if value >= 10000:
        return "A"
    if value >= 8000:
        return "B"
    if value >= 6000:
        return "C"
    return "D"


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


def parse_number_for_record(field: str, value: Any, errors: list[str], default: float = 0) -> float:
    if value is None or value == "":
        return default
    parsed = parse_number(value, default=None)
    if parsed is None:
        errors.append(f"{field}: 数値として読み取れませんでした（入力値: {value}）")
        return default
    return parsed


def parse_weight_for_record(value: Any) -> float:
    parsed = parse_optional_positive_number(value)
    return parsed if parsed is not None else 0


def is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def normalize_training_detail(value: Any) -> str:
    if is_blank_value(value):
        return ""
    if isinstance(value, (list, tuple)):
        parts = [normalize_training_detail(item) for item in value]
        return " / ".join(part for part in parts if part)
    if isinstance(value, dict):
        exercise = value.get("exercise") or value.get("種目") or value.get("name")
        result = value.get("result") or value.get("結果") or value.get("sets") or value.get("reps")
        if exercise or result:
            return " ".join(str(part).strip() for part in [exercise, result] if not is_blank_value(part))

        for key in ["menu", "detail", "details", "training_detail", "workout_detail", "筋トレ内容"]:
            if key in value:
                return normalize_training_detail(value[key])
    return str(value).strip()


def substantive_training_detail(value: Any) -> str:
    detail = normalize_training_detail(value)
    if detail.lower() in {"あり", "true", "yes", "y", "1", "done"}:
        return ""
    if detail in {"有", "実施", "した"}:
        return ""
    return detail


def normalize_yes_no(value: Any) -> str:
    if is_blank_value(value):
        return "なし"
    if isinstance(value, bool):
        return "あり" if value else "なし"
    if isinstance(value, dict):
        for key in ["performed", "trained", "done", "筋トレ有無", "実施"]:
            if key in value:
                return normalize_yes_no(value[key])
        detail = normalize_training_detail(value)
        return "あり" if detail else "なし"

    text = str(value).strip()
    if not text:
        return "なし"
    lowered = text.lower()
    if lowered in {"true", "yes", "y", "1", "done"} or "true" in lowered:
        return "あり"
    if lowered in {"false", "no", "n", "0", "none", "なし", "休み", "してない"} or "false" in lowered:
        return "なし"
    if lowered in {"true", "yes", "y", "1", "done", "あり", "実施", "した"}:
        return "あり"
    if any(word in text for word in ["なし", "無", "休み", "してない"]):
        return "なし"
    if any(word in text for word in ["あり", "有", "実施", "した"]):
        return "あり"
    return text


def training_performed(value: Any) -> bool:
    return normalize_yes_no(value) == "あり"


def training_counted(row: dict[str, Any] | pd.Series) -> bool:
    if not training_performed(row.get("筋トレ有無")):
        return False
    return bool(substantive_training_detail(row.get("筋トレ内容")) or substantive_training_detail(row.get("筋トレ有無")))


def fill_body_scores(row: dict[str, Any]) -> dict[str, Any]:
    auto_scores = calculate_bodyos_score(row)
    manual_score = parse_number(row.get("Body Score"), default=0)
    if manual_score > 0 and parse_number(row.get("手動Body Score"), default=0) <= 0:
        row["手動Body Score"] = int(manual_score)

    for column in SCORE_COMPONENTS:
        row[column] = auto_scores[column]

    row["Body Score"] = auto_scores["Body Score"]
    row["Body Score種別"] = "auto"
    return row


def recalculate_body_scores(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    if data.empty:
        return data

    for index, row in data.iterrows():
        filled = fill_body_scores(row.to_dict())
        for column in BODY_SCORE_COLUMNS + ["手動Body Score", "Body Score種別"]:
            data.at[index, column] = filled[column]
    return data


def ensure_body_scores(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    if data.empty:
        return data

    missing_columns = [column for column in BODY_SCORE_COLUMNS if column not in data.columns]
    needs_initial_score = bool(missing_columns)
    if not needs_initial_score:
        score_values = pd.to_numeric(data["Body Score"], errors="coerce").fillna(0)
        needs_initial_score = bool((score_values <= 0).any())

    return recalculate_body_scores(data) if needs_initial_score else data


def normalize_date(value: Any) -> pd.Timestamp:
    if value is None or value == "":
        raise ValueError("日付がありません")
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"日付を読み取れませんでした: {value}")
    return parsed.normalize()


def get_nested_value(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data:
            return data[key]
        if "." in key:
            current: Any = data
            for part in key.split("."):
                if not isinstance(current, dict) or part not in current:
                    current = None
                    break
                current = current[part]
            if current is not None:
                return current

    meals = data.get("食事") or data.get("meals")
    if isinstance(meals, dict):
        for key in keys:
            if key in meals:
                return meals[key]

    training = data.get("筋トレ") or data.get("training") or data.get("workout")
    if isinstance(training, dict):
        for key in keys:
            if key in training:
                return training[key]

    return None


def normalize_record(raw: dict[str, Any], record_number: int = 1) -> dict[str, Any]:
    row = {column: "" for column in COLUMNS}
    errors: list[str] = []

    for column, aliases in JSON_KEY_ALIASES.items():
        value = get_nested_value(raw, aliases)
        if value is not None:
            row[column] = value

    try:
        row["日付"] = normalize_date(row["日付"])
    except ValueError as exc:
        errors.append(f"日付: {exc}")

    row["体重"] = parse_weight_for_record(row["体重"])
    row["歩数"] = int(parse_number_for_record("歩数", row["歩数"], errors))
    row["歩数ランク"] = rank_steps(row["歩数"])
    row["睡眠時間"] = parse_number_for_record("睡眠時間", row["睡眠時間"], errors)
    row["モード"] = normalize_mode(row["モード"])
    row["筋トレ有無"] = normalize_yes_no(row["筋トレ有無"])
    row["筋トレ内容"] = normalize_training_detail(row["筋トレ内容"])
    row["今日の採点"] = int(parse_number_for_record("今日の採点", row["今日の採点"], errors))
    row["イベント名"] = "" if row["イベント名"] is None else str(row["イベント名"])

    for column in ["朝", "昼", "夜", "間食", "仕事中のドリンク", "筋トレ内容", "体調", "飲酒", "飲酒内容", "飲酒レベル", "コメント"]:
        row[column] = "" if row[column] is None else str(row[column])

    breakfast_detail = estimate_calorie_detail(row["朝"], "朝")
    lunch_detail = estimate_calorie_detail(row["昼"], "昼")
    dinner_detail = estimate_calorie_detail(row["夜"], "夜")
    snacks_detail = estimate_calorie_detail(row["間食"], "間食")
    drinks_detail = estimate_calorie_detail(row["仕事中のドリンク"], "仕事中のドリンク")

    row["朝カロリー(kcal)"] = int(breakfast_detail["kcal"])
    row["昼カロリー(kcal)"] = int(lunch_detail["kcal"])
    row["夜カロリー(kcal)"] = int(dinner_detail["kcal"])
    row["間食カロリー(kcal)"] = int(snacks_detail["kcal"])
    row["ドリンクカロリー(kcal)"] = int(drinks_detail["kcal"])
    row["カロリー推定信頼度"] = calorie_confidence_for_entered_meals(
        (row["朝"], breakfast_detail),
        (row["昼"], lunch_detail),
        (row["夜"], dinner_detail),
        (row["間食"], snacks_detail),
        (row["仕事中のドリンク"], drinks_detail),
    )

    estimated = parse_number_for_record("推定摂取カロリー", row["推定摂取カロリー"], errors)
    if estimated <= 0:
        estimated = sum(
            int(row[column])
            for column in [
                "朝カロリー(kcal)",
                "昼カロリー(kcal)",
                "夜カロリー(kcal)",
                "間食カロリー(kcal)",
                "ドリンクカロリー(kcal)",
            ]
        )
    row["推定摂取カロリー"] = int(estimated)
    row = fill_body_scores(row)

    if errors:
        raise RecordValidationError([f"{record_number}件目の{message}" for message in errors])

    return row


def normalize_columns(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    for old_column, new_column in COLUMN_ALIASES.items():
        if old_column in data.columns and new_column not in data.columns:
            data[new_column] = data[old_column]

    for column in COLUMNS:
        if column not in data.columns:
            data[column] = "" if column in TEXT_COLUMNS else 0

    data["筋トレ内容"] = data.apply(
        lambda row: substantive_training_detail(row["筋トレ内容"]) or substantive_training_detail(row["筋トレ有無"]),
        axis=1,
    )
    original_training_status_blank = data["筋トレ有無"].apply(is_blank_value)
    data["筋トレ有無"] = data["筋トレ有無"].apply(normalize_yes_no)
    data.loc[original_training_status_blank & data["筋トレ内容"].astype(bool), "筋トレ有無"] = "あり"
    data["モード"] = data["モード"].apply(normalize_mode)

    return data[COLUMNS]


def load_data() -> pd.DataFrame:
    if github_storage_enabled():
        try:
            csv_text, _ = read_github_records()
            loaded = pd.read_csv(StringIO(csv_text)) if csv_text else pd.DataFrame(columns=COLUMNS)
        except Exception as exc:
            st.error(f"GitHub上のrecords.csvを読み込めませんでした: {exc}")
            loaded = pd.DataFrame(columns=COLUMNS)
    elif Path(DATA_FILE).exists():
        loaded = pd.read_csv(DATA_FILE)
    else:
        loaded = pd.DataFrame(columns=COLUMNS)

    loaded = normalize_columns(loaded)

    if not loaded.empty:
        loaded["日付"] = pd.to_datetime(loaded["日付"], errors="coerce")
        loaded = loaded.dropna(subset=["日付"])
        for column in NUMERIC_COLUMNS:
            loaded[column] = pd.to_numeric(loaded[column], errors="coerce")
            if column not in SCORE_COMPONENTS:
                loaded[column] = loaded[column].fillna(0)
        loaded["歩数"] = loaded["歩数"].astype(int)
        loaded["推定摂取カロリー"] = loaded["推定摂取カロリー"].astype(int)
        loaded["今日の採点"] = loaded["今日の採点"].astype(int)
        loaded["Body Score"] = loaded["Body Score"].fillna(0).astype(int)
        loaded["モード"] = loaded["モード"].apply(normalize_mode)
        loaded["歩数ランク"] = loaded["歩数"].apply(rank_steps)
        loaded = ensure_body_scores(loaded)
        loaded = loaded.sort_values("日付")

    return loaded


def csv_text_from_data(data: pd.DataFrame) -> str:
    data = normalize_columns(data)
    return data.to_csv(index=False)


def save_data(data: pd.DataFrame) -> None:
    data = normalize_columns(data)
    csv_text = csv_text_from_data(data)
    if github_storage_enabled():
        write_github_records(csv_text)

    data.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")


def upsert_records(data: pd.DataFrame, rows: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    data = normalize_columns(data)
    rows = normalize_columns(rows)

    data["_date_key"] = pd.to_datetime(data["日付"], errors="coerce").dt.strftime("%Y-%m-%d")
    rows["_date_key"] = pd.to_datetime(rows["日付"], errors="coerce").dt.strftime("%Y-%m-%d")
    existing_keys = set(data["_date_key"].dropna())
    updated = int(rows["_date_key"].isin(existing_keys).sum())
    added = int((~rows["_date_key"].isin(existing_keys)).sum())

    data = data[~data["_date_key"].isin(rows["_date_key"])]
    combined = pd.concat([data.drop(columns=["_date_key"]), rows.drop(columns=["_date_key"])], ignore_index=True)
    combined["歩数ランク"] = combined["歩数"].apply(rank_steps)
    combined = ensure_body_scores(combined)
    combined = combined.sort_values("日付")
    return normalize_columns(combined), added, updated


def predict_target_date(data: pd.DataFrame, target_weight: float) -> str:
    valid_data = data.copy()
    valid_data["有効体重"] = valid_weight_series(valid_data["体重"])
    valid_data = valid_data.dropna(subset=["有効体重"])

    if len(valid_data) < 2:
        return "予測には2件以上の記録が必要です。"

    recent = valid_data.tail(min(len(valid_data), 14)).copy()
    first_weight = float(recent["有効体重"].iloc[0])
    latest_weight = float(recent["有効体重"].iloc[-1])
    days_elapsed = max((recent["日付"].iloc[-1] - recent["日付"].iloc[0]).days, 1)
    daily_pace = (first_weight - latest_weight) / days_elapsed

    if latest_weight <= target_weight:
        return f"すでに目標の{target_weight:.1f}kgを達成しています。"
    if daily_pace <= 0:
        return "直近データでは体重が減っていないため、到達日はまだ予測できません。"

    days_needed = int((latest_weight - target_weight) / daily_pace)
    target_date = dt.date.today() + dt.timedelta(days=days_needed)
    return f"現在ペースなら、約{days_needed}日後（{target_date.strftime('%Y/%m/%d')}）に{target_weight:.1f}kg到達見込みです。"


df = load_data()
storage_config = github_storage_config()
if github_storage_enabled():
    st.caption(f"保存先: GitHub `{storage_config['repository']}/{storage_config['path']}` ({storage_config['branch']})")
else:
    st.caption("保存先: ローカル records.csv（Streamlit Cloudで永続化するにはGitHub保存用のsecretsを設定してください）")

if df.empty:
    st.info("まだ記録がありません。まずは今日の記録を保存してみましょう。")
else:
    df = df.sort_values("日付")
    df = ensure_body_scores(df)
    render_dashboard(
        df,
        TARGET_WEIGHT,
        predict_target_date,
        training_counted,
        food_knowledge=current_food_knowledge(),
    )

st.header("今日の記録")
with st.form("daily_record_form"):
    basic_col1, basic_col2 = st.columns(2)
    with basic_col1:
        record_date = st.date_input("日付", value=dt.date.today())
        mode = st.selectbox("モード", MODES, help="NORMAL=通常日 / EVENT=イベント日 / RECOVERY=体調回復日 / BULK=増量期")
        weight = st.number_input("朝の体重(kg)", min_value=40.0, max_value=150.0, value=85.0, step=0.1)
        sleep_hours = st.number_input("睡眠時間", min_value=0.0, max_value=24.0, value=7.0, step=0.5)
    with basic_col2:
        event_name = st.text_input("イベント名", placeholder="例：焼肉、飲み会、旅行、デート")
        steps = st.number_input("歩数", min_value=0, max_value=50000, value=7000, step=500)
        condition = st.text_input("体調", placeholder="例：良い / やや疲れ / 眠い")
        alcohol = st.selectbox("飲酒", ["なし", "あり"])
        alcohol_level = st.selectbox("飲酒レベル", ["なし", "軽い", "通常", "重い"])
        alcohol_detail = st.text_input("飲酒内容", placeholder="例：ビール1杯、濃いめハイボール7杯")

    st.subheader("食べたもの")
    st.caption("自動推定がずれる場合は、右側のカロリー欄へ手入力してください。手入力がある場合はそちらを優先します。")

    meal_col1, meal_col2 = st.columns(2)
    with meal_col1:
        breakfast = st.text_area("朝", placeholder="例：トマトジュース、ゆでたまご", height=80)
        breakfast_kcal_manual = st.number_input("朝カロリー 手入力（任意）", min_value=0, max_value=3000, value=0, step=50)

        lunch = st.text_area("昼", placeholder="例：ぶっかけうどん、とり天1個", height=80)
        lunch_kcal_manual = st.number_input("昼カロリー 手入力（任意）", min_value=0, max_value=4000, value=0, step=50)

        snacks = st.text_area("間食", placeholder="例：菓子123kcal、オイコス", height=80)
        snacks_kcal_manual = st.number_input("間食カロリー 手入力（任意）", min_value=0, max_value=3000, value=0, step=50)

    with meal_col2:
        dinner = st.text_area("夜", placeholder="例：赤飯おにぎり、グリルチキン、オイコス", height=80)
        dinner_kcal_manual = st.number_input("夜カロリー 手入力（任意）", min_value=0, max_value=5000, value=0, step=50)

        work_drinks = st.text_area("仕事中のドリンク", placeholder="例：コーヒー、カフェラテ、プロテイン", height=80)
        drinks_kcal_manual = st.number_input("ドリンクカロリー 手入力（任意）", min_value=0, max_value=2000, value=0, step=50)

    st.subheader("筋トレ")
    trained = st.checkbox("筋トレした")
    training_detail = st.text_area(
        "筋トレ内容",
        placeholder="例：ベンチプレス 90kg 5,6,6,4 / 腹筋 10,10,5 / サイドレイズ 12kg 15回",
        height=120,
    )
    bench = st.number_input("ベンチプレス最高重量(kg)", min_value=0.0, max_value=250.0, value=90.0, step=2.5)

    score = st.slider("今日の採点", min_value=0, max_value=100, value=70, step=5)
    comment = st.text_area("コメント", placeholder="例：空腹感は少なめ。明日は歩数を増やす。", height=80)

    submitted = st.form_submit_button("CSVに保存する")

if submitted:
    breakfast_detail = estimate_calorie_detail(breakfast, "朝")
    lunch_detail = estimate_calorie_detail(lunch, "昼")
    dinner_detail = estimate_calorie_detail(dinner, "夜")
    snacks_detail = estimate_calorie_detail(snacks, "間食")
    drinks_detail = estimate_calorie_detail(work_drinks, "仕事中のドリンク")

    breakfast_kcal = final_kcal(int(breakfast_detail["kcal"]), breakfast_kcal_manual)
    lunch_kcal = final_kcal(int(lunch_detail["kcal"]), lunch_kcal_manual)
    dinner_kcal = final_kcal(int(dinner_detail["kcal"]), dinner_kcal_manual)
    snacks_kcal = final_kcal(int(snacks_detail["kcal"]), snacks_kcal_manual)
    drinks_kcal = final_kcal(int(drinks_detail["kcal"]), drinks_kcal_manual)
    calorie_confidence = calorie_confidence_for_entered_meals(
        (breakfast, {"confidence": final_confidence(str(breakfast_detail["confidence"]), breakfast_kcal_manual)}),
        (lunch, {"confidence": final_confidence(str(lunch_detail["confidence"]), lunch_kcal_manual)}),
        (dinner, {"confidence": final_confidence(str(dinner_detail["confidence"]), dinner_kcal_manual)}),
        (snacks, {"confidence": final_confidence(str(snacks_detail["confidence"]), snacks_kcal_manual)}),
        (work_drinks, {"confidence": final_confidence(str(drinks_detail["confidence"]), drinks_kcal_manual)}),
    )
    estimated_calories = breakfast_kcal + lunch_kcal + dinner_kcal + snacks_kcal + drinks_kcal

    record = fill_body_scores(
        {
            "日付": pd.to_datetime(record_date),
            "モード": mode,
            "イベント名": event_name,
            "体重": weight,
            "歩数": steps,
            "歩数ランク": rank_steps(steps),
            "睡眠時間": sleep_hours,
            "朝": breakfast,
            "昼": lunch,
            "夜": dinner,
            "間食": snacks,
            "仕事中のドリンク": work_drinks,
            "推定摂取カロリー": estimated_calories,
            "筋トレ有無": "あり" if trained else "なし",
            "筋トレ内容": training_detail,
            "体調": condition,
            "飲酒": alcohol,
            "飲酒内容": alcohol_detail,
            "飲酒レベル": alcohol_level,
            "今日の採点": score,
            "コメント": comment,
            "朝カロリー(kcal)": breakfast_kcal,
            "昼カロリー(kcal)": lunch_kcal,
            "夜カロリー(kcal)": dinner_kcal,
            "間食カロリー(kcal)": snacks_kcal,
            "ドリンクカロリー(kcal)": drinks_kcal,
            "ベンチプレス(kg)": bench if trained else 0,
            "カロリー推定信頼度": calorie_confidence,
        }
    )
    new_row = pd.DataFrame([record])
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values("日付")
    try:
        save_data(df)
        try:
            food_summary = remember_saved_meals(
                [
                    ("朝", breakfast, breakfast_detail),
                    ("昼", lunch, lunch_detail),
                    ("夜", dinner, dinner_detail),
                    ("間食", snacks, snacks_detail),
                    ("仕事中のドリンク", work_drinks, drinks_detail),
                ],
                record_date=record_date.isoformat(),
                operation_id=f"manual-save:{record_date.isoformat()}",
                used_at=pd.to_datetime(record_date).isoformat(),
            )
        except Exception as exc:
            food_summary = empty_food_resolution_summary()
            st.warning(f"CSVは保存しましたが、Personal Food Masterの記録に失敗しました: {exc}")
        st.success(
            f"CSVへ保存しました。合計カロリーは約{estimated_calories:,}kcal、"
            f"Body Scoreは{record['Body Score']}点です。"
        )
        st.write(
            f"朝 {breakfast_kcal:,}kcal / 昼 {lunch_kcal:,}kcal / 夜 {dinner_kcal:,}kcal / "
            f"間食 {snacks_kcal:,}kcal / ドリンク {drinks_kcal:,}kcal"
        )
        st.write(f"カロリー推定信頼度: {calorie_confidence}")
        if food_summary["encounter_count"]:
            st.caption(f"Personal Food Masterに{food_summary['encounter_count']}件の食品遭遇を記録しました。")
        render_food_import_summary(food_summary)
    except Exception as exc:
        st.error(f"保存に失敗しました: {exc}")

st.header("ChatGPTログ貼り付け")
st.caption("1日分のJSONを貼り付けると、records.csvへ保存します。同じ日付があれば上書きし、なければ追加します。JSON配列なら複数日分も保存できます。")
chatgpt_log = st.text_area(
    "JSON形式のログ",
    placeholder='{"日付":"2026-06-30","mode":"EVENT","event_name":"仕事後の飲み会","weight":84.2,"steps":3493,"sleep_hours":3.83,"condition":7,"workout":false,"alcohol":"あり","alcohol_detail":"ビール1杯、濃いめハイボール約7杯","meal":"魚料理中心、飲み会前にグリルチキン・紅鮭おにぎり・半熟ゆで卵","推定摂取カロリー":2081,"コメント":"Body Scoreは省略してアプリ側で自動計算"}',
    height=220,
)

if st.button("ChatGPTログをCSVに追加"):
    try:
        parsed = json.loads(chatgpt_log)
        records = parsed if isinstance(parsed, list) else [parsed]
        if not records:
            raise ValueError("JSON配列が空です。1件以上のログを入れてください。")
        if not all(isinstance(record, dict) for record in records):
            raise ValueError("JSONはオブジェクト、またはオブジェクトの配列にしてください。")

        normalized_records = []
        validation_errors = []
        for index, record in enumerate(records, start=1):
            try:
                normalized_records.append(normalize_record(record, record_number=index))
            except RecordValidationError as exc:
                validation_errors.extend(exc.errors)
        if validation_errors:
            raise RecordValidationError(validation_errors)

        imported_rows = pd.DataFrame(normalized_records)
        df, added_count, updated_count = upsert_records(df, imported_rows)
        save_data(df)
        food_summary = empty_food_resolution_summary()
        try:
            for imported_record in normalized_records:
                imported_summary = remember_saved_meals(
                    [
                        (meal_type, str(imported_record.get(column, "")), {})
                        for meal_type, column in [
                            ("朝", "朝"),
                            ("昼", "昼"),
                            ("夜", "夜"),
                            ("間食", "間食"),
                            ("仕事中のドリンク", "仕事中のドリンク"),
                        ]
                    ],
                    record_date=pd.to_datetime(imported_record["日付"]).date().isoformat(),
                    operation_id=f"json-import:{pd.to_datetime(imported_record['日付']).date().isoformat()}",
                    used_at=pd.to_datetime(imported_record["日付"]).isoformat(),
                )
                merge_food_resolution_summary(food_summary, imported_summary)
        except Exception as exc:
            st.warning(f"CSVは保存しましたが、Personal Food Masterの記録に失敗しました: {exc}")
        st.success(
            f"{len(imported_rows)}件のChatGPTログをrecords.csvへ保存しました。"
            f"追加: {added_count}件 / 上書き: {updated_count}件"
        )
        if food_summary["encounter_count"]:
            st.caption(f"Personal Food Masterに{food_summary['encounter_count']}件の食品遭遇を記録しました。")
        render_food_import_summary(food_summary)
    except json.JSONDecodeError as exc:
        st.error(f"JSONの形式を確認してください: {exc}")
    except RecordValidationError as exc:
        st.error("読み取れなかった項目があります。")
        for message in exc.errors:
            st.write(f"- {message}")
    except Exception as exc:
        st.error(f"取り込みに失敗しました: {exc}")

if not df.empty:
    st.header("メンテナンス")
    if st.button("Body Scoreを再計算"):
        try:
            df = recalculate_body_scores(df)
            save_data(df)
            st.success("全レコードのBody Scoreと内訳スコアを最新ロジックで再計算しました。")
        except Exception as exc:
            st.error(f"Body Scoreの再計算に失敗しました: {exc}")

render_food_knowledge_dashboard(PERSONAL_FOOD_REPOSITORY, PERSONAL_FOOD_USER_ID)
render_food_master_management(PERSONAL_FOOD_REPOSITORY, PERSONAL_FOOD_USER_ID)

st.caption("注意: カロリーは概算です。正確にしたい日は手入力欄を使ってください。")
