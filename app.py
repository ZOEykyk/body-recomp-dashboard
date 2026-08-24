from __future__ import annotations

import datetime as dt
import base64
import html
import json
import logging
import os
import re
import tempfile
import time
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
from bodyos_import import (
    ImportValidationError as BodyOSImportValidationError,
    canonical_document_payload,
    canonical_to_projection,
    export_projection,
    import_document_fingerprint,
    operation_import_id,
    parse_import_json,
    preview_import,
    resolve_record_nutrition,
    structured_import_log,
)
from data_integrity import (
    parse_optional_positive_number,
    valid_weight_series,
)
from dashboard import render_dashboard
from food_master_repository import JsonFoodMasterRepository
from food_knowledge_diagnostics import repository_runtime_diagnostics
from food_repository_factory import create_food_master_repository
from food_master_models import meal_content_fingerprint
from food_master_ui import render_food_master_management
from food_knowledge_dashboard import render_food_knowledge_dashboard
from food_parser import parse_food_text
from food_resolver import RESOLUTION_ORIGINS, build_food_knowledge_snapshot, resolve_food_text
from personal_food_master import remember_food_encounters_with_summary
from performance_instrumentation import PERFORMANCE, instrument, measure, performance_debug_enabled
from runtime_cache import clear_cached_function, streamlit_cache
from schema_contract import load_canonical_example
from smart_food_capture import (
    canonical_builder_result,
    canonical_workout_from_text,
    candidates_from_resolution,
    prepare_capture_item,
    unknown_candidate,
)
from smart_food_capture_ui import (
    CAPTURE_STATE_KEY,
    render_food_knowledge_debug_panel,
    render_smart_food_capture,
)

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
    "タンパク質(g)",
    "脂質(g)",
    "炭水化物(g)",
    "カロリー不明件数",
    "筋トレセッション数",
    "筋トレ種目数",
    "筋トレセット数",
    "筋トレ時間(分)",
    "構造化食事JSON",
    "構造化筋トレJSON",
    "Import ID",
    "Import Schema Version",
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
    "構造化食事JSON",
    "構造化筋トレJSON",
    "Import ID",
    "Import Schema Version",
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
    "タンパク質(g)",
    "脂質(g)",
    "炭水化物(g)",
    "カロリー不明件数",
    "筋トレセッション数",
    "筋トレ種目数",
    "筋トレセット数",
    "筋トレ時間(分)",
]

NULLABLE_NUMERIC_COLUMNS = {
    "推定摂取カロリー",
    "朝カロリー(kcal)",
    "昼カロリー(kcal)",
    "夜カロリー(kcal)",
    "間食カロリー(kcal)",
    "ドリンクカロリー(kcal)",
    "タンパク質(g)",
    "脂質(g)",
    "炭水化物(g)",
    "筋トレ時間(分)",
}

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


def streamlit_session_state() -> Any:
    state = getattr(st, "session_state", None)
    return state if hasattr(state, "get") and hasattr(state, "__setitem__") else {}


def food_repository_config() -> dict[str, str]:
    names = [
        "FOOD_KNOWLEDGE_REPOSITORY",
        "FOOD_KNOWLEDGE_MODE",
        "FOOD_KNOWLEDGE_USER_ID",
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_TIMEOUT_SECONDS",
    ]
    return {name: get_config_value(name) for name in names}


PERSONAL_FOOD_USER_ID = get_config_value("FOOD_KNOWLEDGE_USER_ID", DEFAULT_PERSONAL_FOOD_USER_ID)


@streamlit_cache(st, "cache_resource", show_spinner=False)
def build_personal_food_repository():
    """Create one process-level repository/client without putting secrets in a cache key."""
    local_repository = JsonFoodMasterRepository(
        Path(__file__).with_name(PERSONAL_FOOD_MASTER_FILE),
        Path(__file__).with_name(FOOD_ENCOUNTERS_FILE),
    )
    return create_food_master_repository(food_repository_config(), local_repository)


PERSONAL_FOOD_REPOSITORY = build_personal_food_repository()


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


@streamlit_cache(st, "cache_data", ttl=30, max_entries=32, show_spinner=False)
def cached_personal_foods(user_id: str, repository_revision: int) -> list[dict[str, Any]]:
    del repository_revision
    return PERSONAL_FOOD_REPOSITORY.build_snapshot(user_id)["personal_foods"]


@streamlit_cache(st, "cache_data", ttl=3600, show_spinner=False)
def cached_static_food_knowledge() -> dict[str, Any]:
    return build_food_knowledge_snapshot([])


def current_food_knowledge() -> dict[str, Any]:
    revision = PERSONAL_FOOD_REPOSITORY.cache_revision()
    try:
        with measure("food_knowledge.personal_snapshot", repository_revision=revision):
            personal_foods = cached_personal_foods(PERSONAL_FOOD_USER_ID, revision)
    except Exception as exc:
        LOGGER.warning("Food Knowledge read failed: %s", type(exc).__name__)
        personal_foods = []
    with measure("food_knowledge.static_snapshot"):
        static = cached_static_food_knowledge()
    return {
        "metadata": static["metadata"],
        "personal_foods": personal_foods,
        "official_catalog": static["official_catalog"],
        "generic_catalog": static["generic_catalog"],
    }


def invalidate_personal_food_cache() -> None:
    """Make confirmed Food Knowledge visible on the immediately following rerun."""
    clear_cached_function(cached_personal_foods)


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
    knowledge: dict[str, Any] | None = None,
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
            resolution = resolve_food_text(
                str(text),
                meal_type,
                knowledge=knowledge if knowledge is not None else current_food_knowledge(),
            )
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


def render_schema_validation_errors(exc: BodyOSImportValidationError) -> None:
    st.error(f"Schema Validation Error: {len(exc.errors)}件。保存は実行されていません。")
    issues = exc.issues or [
        {
            "path": "$",
            "message": message,
            "suggestion": None,
            "auto_fixable": False,
        }
        for message in exc.errors
    ]
    cards = []
    for issue in issues:
        suggestion = issue.get("suggestion") or "入力側でSchema 1.0に合わせて修正してください。"
        auto_fix = "可能" if issue.get("auto_fixable") else "不可"
        cards.append(
            "<div class='bodyos-schema-error-card'>"
            f"<div class='bodyos-schema-error-path'>{html.escape(str(issue.get('path') or '$'))}</div>"
            f"<div class='bodyos-schema-error-message'>{html.escape(str(issue.get('message') or 'Validation error'))}</div>"
            f"<div class='bodyos-schema-error-suggestion'><strong>修正候補:</strong> {html.escape(str(suggestion))}</div>"
            f"<div class='bodyos-schema-error-auto'>自動修正: {auto_fix}</div>"
            "</div>"
        )
    st.markdown(
        """
        <style>
          .bodyos-schema-errors,
          .bodyos-schema-errors * { box-sizing: border-box; min-width: 0; }
          .bodyos-schema-errors { display: grid; gap: 0.65rem; width: 100%; }
          .bodyos-schema-errors .bodyos-schema-error-card {
            border: 1px solid rgba(220, 53, 69, 0.36); border-radius: 8px;
            padding: 0.75rem 0.85rem; background: rgba(220, 53, 69, 0.06);
            overflow: hidden;
          }
          .bodyos-schema-errors .bodyos-schema-error-path {
            color: #b42318; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-weight: 700; overflow-wrap: anywhere; word-break: break-word;
          }
          .bodyos-schema-errors .bodyos-schema-error-message,
          .bodyos-schema-errors .bodyos-schema-error-suggestion,
          .bodyos-schema-errors .bodyos-schema-error-auto {
            margin-top: 0.38rem; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word;
          }
          .bodyos-schema-errors .bodyos-schema-error-auto { font-size: 0.88rem; opacity: 0.78; }
          @media (max-width: 520px) {
            .bodyos-schema-errors .bodyos-schema-error-card { padding: 0.7rem 0.72rem; }
          }
        </style>
        """ + f"<div class='bodyos-schema-errors'>{''.join(cards)}</div>",
        unsafe_allow_html=True,
    )


def render_normalization_report(changes: list[dict[str, Any]]) -> None:
    if not changes:
        st.success("Canonical Schema 1.0 input。Compatibility normalizationは不要です。")
        return
    st.info(f"Compatibility normalization: {len(changes)} changes")
    rows = "".join(
        "<div class='bodyos-normalization-row'>"
        f"<code>{html.escape(str(change.get('source_path') or '$'))}</code>"
        "<span aria-hidden='true'>→</span>"
        f"<code>{html.escape(str(change.get('target_path') or '$'))}</code>"
        "</div>"
        for change in changes
    )
    st.markdown(
        """
        <style>
          .bodyos-normalization-report,
          .bodyos-normalization-report * { box-sizing: border-box; min-width: 0; }
          .bodyos-normalization-report { display: grid; gap: 0.45rem; width: 100%; }
          .bodyos-normalization-report .bodyos-normalization-row {
            display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
            align-items: center; gap: 0.5rem; padding: 0.55rem 0.65rem;
            border: 1px solid rgba(49, 51, 63, 0.16); border-radius: 6px;
          }
          .bodyos-normalization-report code {
            white-space: normal; overflow-wrap: anywhere; word-break: break-word;
          }
          @media (max-width: 520px) {
            .bodyos-normalization-report .bodyos-normalization-row {
              grid-template-columns: minmax(0, 1fr); gap: 0.2rem;
            }
          }
        </style>
        """ + f"<div class='bodyos-normalization-report'>{rows}</div>",
        unsafe_allow_html=True,
    )


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


def legacy_meal_capture_items(
    text: str,
    detail: dict[str, Any],
    meal_type: str,
    manual_kcal: int,
) -> list[dict[str, Any]]:
    """Adapt the existing free-text workflow into the PR15 capture contract."""
    value = str(text or "").strip()
    if not value:
        return []
    if manual_kcal > 0:
        candidate = unknown_candidate(value, meal_type)
        candidate["display_name"] = value
        candidate["canonical_name"] = value
        return [
            prepare_capture_item(
                candidate,
                meal_type=meal_type,
                quantity=1,
                unit=None,
                consumed_quantity=1,
                nutrition={
                    "basis": "total",
                    "calories_kcal": manual_kcal,
                    "protein_g": None,
                    "fat_g": None,
                    "carbs_g": None,
                    "sugar_g": None,
                    "fiber_g": None,
                    "salt_g": None,
                },
                source_mode="estimated",
                notes="従来自由文の手入力カロリー",
            )
        ]
    candidates = candidates_from_resolution(
        detail.get("food_resolution") or {},
        meal_type,
        accept_fallback_estimate=True,
    )
    return [
        prepare_capture_item(
            candidate,
            meal_type=meal_type,
            quantity=candidate.get("quantity") or 1,
            unit=candidate.get("unit"),
            consumed_quantity=candidate.get("quantity") or 1,
            source_mode="candidate",
            notes="従来自由文入力",
        )
        for candidate in candidates
    ]


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


def normalize_record(
    raw: dict[str, Any],
    record_number: int = 1,
    *,
    food_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    knowledge = food_knowledge if food_knowledge is not None else current_food_knowledge()
    breakfast_detail = estimate_calorie_detail(row["朝"], "朝", knowledge=knowledge)
    lunch_detail = estimate_calorie_detail(row["昼"], "昼", knowledge=knowledge)
    dinner_detail = estimate_calorie_detail(row["夜"], "夜", knowledge=knowledge)
    snacks_detail = estimate_calorie_detail(row["間食"], "間食", knowledge=knowledge)
    drinks_detail = estimate_calorie_detail(row["仕事中のドリンク"], "仕事中のドリンク", knowledge=knowledge)

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
            data[column] = "" if column in TEXT_COLUMNS else pd.NA if column in NULLABLE_NUMERIC_COLUMNS else 0

    for column in TEXT_COLUMNS:
        data[column] = data[column].astype("object")

    data["筋トレ内容"] = data.apply(
        lambda row: substantive_training_detail(row["筋トレ内容"]) or substantive_training_detail(row["筋トレ有無"]),
        axis=1,
    )
    original_training_status_blank = data["筋トレ有無"].apply(is_blank_value)
    data["筋トレ有無"] = data["筋トレ有無"].apply(normalize_yes_no)
    data.loc[original_training_status_blank & data["筋トレ内容"].astype(bool), "筋トレ有無"] = "あり"
    data["モード"] = data["モード"].apply(normalize_mode)

    return data[COLUMNS]


@streamlit_cache(st, "cache_data", ttl=30, max_entries=8, show_spinner=False)
def cached_github_records(repository: str, branch: str, path: str) -> str | None:
    del repository, branch, path
    csv_text, _ = read_github_records()
    return csv_text


@streamlit_cache(st, "cache_data", max_entries=8, show_spinner=False)
def cached_local_records(path: str, modified_ns: int, size: int) -> str:
    del modified_ns, size
    return Path(path).read_text(encoding="utf-8-sig")


@streamlit_cache(st, "cache_data", max_entries=8, show_spinner=False)
def normalized_records_from_csv(csv_text: str) -> pd.DataFrame:
    loaded = pd.read_csv(StringIO(csv_text)) if csv_text else pd.DataFrame(columns=COLUMNS)
    loaded = normalize_columns(loaded)

    if not loaded.empty:
        loaded["日付"] = pd.to_datetime(loaded["日付"], errors="coerce")
        loaded = loaded.dropna(subset=["日付"])
        for column in NUMERIC_COLUMNS:
            loaded[column] = pd.to_numeric(loaded[column], errors="coerce")
            if column not in SCORE_COMPONENTS and column not in NULLABLE_NUMERIC_COLUMNS:
                loaded[column] = loaded[column].fillna(0)
        loaded["歩数"] = loaded["歩数"].astype(int)
        loaded["今日の採点"] = loaded["今日の採点"].astype(int)
        loaded["Body Score"] = loaded["Body Score"].fillna(0).astype(int)
        loaded["モード"] = loaded["モード"].apply(normalize_mode)
        loaded["歩数ランク"] = loaded["歩数"].apply(rank_steps)
        loaded = ensure_body_scores(loaded)
        loaded = loaded.sort_values("日付")

    return loaded


def load_data() -> pd.DataFrame:
    csv_text: str | None = None
    if github_storage_enabled():
        try:
            config = github_storage_config()
            csv_text = cached_github_records(config["repository"], config["branch"], config["path"])
        except Exception as exc:
            st.error(f"GitHub上のrecords.csvを読み込めませんでした: {exc}")
            csv_text = None
    elif Path(DATA_FILE).exists():
        path = Path(DATA_FILE)
        stat = path.stat()
        csv_text = cached_local_records(str(path.resolve()), stat.st_mtime_ns, stat.st_size)

    with measure("records.load_and_normalize", source="github" if github_storage_enabled() else "local"):
        return normalized_records_from_csv(csv_text or "")


def csv_text_from_data(data: pd.DataFrame) -> str:
    data = normalize_columns(data)
    return data.to_csv(index=False)


@instrument("records.save")
def save_data(data: pd.DataFrame) -> None:
    data = normalize_columns(data)
    csv_text = csv_text_from_data(data)
    if github_storage_enabled():
        write_github_records(csv_text)

    destination = Path(DATA_FILE)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(csv_text, encoding="utf-8-sig")
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    clear_cached_function(cached_github_records)
    clear_cached_function(cached_local_records)
    clear_cached_function(normalized_records_from_csv)


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


IMPORT_SECTION_COLUMNS = {
    "weight": {"体重"},
    "sleep": {"睡眠時間"},
    "condition": {"体調"},
    "steps": {"歩数", "歩数ランク"},
    "notes": {"コメント"},
    "mode": {"モード"},
    "event_name": {"イベント名"},
    "alcohol": {"飲酒", "飲酒内容", "飲酒レベル"},
    "workout": {
        "筋トレ有無",
        "筋トレ内容",
        "筋トレセッション数",
        "筋トレ種目数",
        "筋トレセット数",
        "筋トレ時間(分)",
        "構造化筋トレJSON",
    },
    "meals": {
        "朝",
        "昼",
        "夜",
        "間食",
        "仕事中のドリンク",
        "朝カロリー(kcal)",
        "昼カロリー(kcal)",
        "夜カロリー(kcal)",
        "間食カロリー(kcal)",
        "ドリンクカロリー(kcal)",
        "構造化食事JSON",
        "カロリー不明件数",
        "推定摂取カロリー",
        "タンパク質(g)",
        "脂質(g)",
        "炭水化物(g)",
        "カロリー推定信頼度",
    },
    "nutrition": {
        "推定摂取カロリー",
        "タンパク質(g)",
        "脂質(g)",
        "炭水化物(g)",
        "カロリー推定信頼度",
    },
}


def build_import_rows(
    document: dict[str, Any],
    *,
    food_knowledge: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    projected_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    knowledge = food_knowledge if food_knowledge is not None else current_food_knowledge()
    for record in document.get("records") or []:
        nutrition = resolve_record_nutrition(
            record,
            lambda text, meal_type: resolve_food_text(text, meal_type, knowledge=knowledge),
        )
        projection = canonical_to_projection(record, nutrition)
        projection["日付"] = normalize_date(projection["日付"])
        projection["歩数ランク"] = rank_steps(projection.get("歩数"))
        projection["カロリー推定信頼度"] = (
            "high"
            if nutrition["unknown_calorie_count"] == 0
            else "medium"
            if nutrition["unknown_calorie_count"] <= 2
            else "low"
        )
        normalized = {column: "" if column in TEXT_COLUMNS else pd.NA if column in NULLABLE_NUMERIC_COLUMNS else 0 for column in COLUMNS}
        normalized.update(projection)
        projected_rows.append(fill_body_scores(normalized))
        diagnostics.append(
            {
                "date": record["date"],
                "meal_items": sum(
                    len((nutrition.get("meals", {}).get(meal_type) or {}).get("items") or [])
                    for meal_type in ["breakfast", "lunch", "dinner", "snacks", "drinks"]
                ),
                "unknown_calorie_count": nutrition["unknown_calorie_count"],
                "provided_sections": set(record.get("_provided_sections") or []),
            }
        )
    return projected_rows, diagnostics


def apply_import_rows(
    data: pd.DataFrame,
    rows: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    conflict_policy: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    if conflict_policy not in {"update", "replace", "cancel"}:
        raise ValueError(f"Unsupported conflict policy: {conflict_policy}")
    result = normalize_columns(data).copy()
    result["_date_key"] = pd.to_datetime(result["日付"], errors="coerce").dt.strftime("%Y-%m-%d")
    counts = {"added": 0, "updated": 0, "replaced": 0, "skipped": 0}
    for row, diagnostic in zip(rows, diagnostics):
        date_key = pd.to_datetime(row["日付"]).strftime("%Y-%m-%d")
        matches = result.index[result["_date_key"] == date_key].tolist()
        if not matches:
            new_row = {column: row.get(column) for column in COLUMNS}
            new_row["_date_key"] = date_key
            new_frame = pd.DataFrame([new_row], columns=[*COLUMNS, "_date_key"])
            result = new_frame if result.empty else pd.concat([result, new_frame], ignore_index=True)
            counts["added"] += 1
            continue
        if conflict_policy == "cancel":
            counts["skipped"] += 1
            continue

        index = matches[-1]
        if conflict_policy == "replace":
            for column in COLUMNS:
                result.at[index, column] = row.get(column)
            counts["replaced"] += 1
        else:
            columns = {"Import ID", "Import Schema Version"}
            for section in diagnostic["provided_sections"]:
                columns.update(IMPORT_SECTION_COLUMNS.get(section, set()))
            for column in columns:
                if column in row:
                    result.at[index, column] = row.get(column)
            recalculated = fill_body_scores(result.loc[index, COLUMNS].to_dict())
            for column in BODY_SCORE_COLUMNS + ["Body Score種別"]:
                result.at[index, column] = recalculated.get(column)
            counts["updated"] += 1
    result = result.drop(columns=["_date_key"]).sort_values("日付")
    return normalize_columns(result), counts


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


with measure("app.bootstrap"):
    df = load_data()
    active_food_knowledge = current_food_knowledge()
food_knowledge_runtime = repository_runtime_diagnostics(
    PERSONAL_FOOD_REPOSITORY,
    PERSONAL_FOOD_USER_ID,
    active_food_knowledge,
    cached_personal_food_count=len(active_food_knowledge.get("personal_foods") or []),
)
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
        food_knowledge=active_food_knowledge,
    )

st.header("今日の記録")
smart_capture_items = render_smart_food_capture(
    PERSONAL_FOOD_REPOSITORY,
    PERSONAL_FOOD_USER_ID,
    active_food_knowledge,
    on_food_knowledge_changed=invalidate_personal_food_cache,
    runtime_diagnostics=food_knowledge_runtime,
)
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

    with st.expander("従来の自由文入力（互換）", expanded=False):
        st.caption("Smart Food Captureを使わない記録向けです。手入力カロリーは概算値として扱います。")
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

    breakfast_detail = estimate_calorie_detail(breakfast, "朝", knowledge=active_food_knowledge)
    lunch_detail = estimate_calorie_detail(lunch, "昼", knowledge=active_food_knowledge)
    dinner_detail = estimate_calorie_detail(dinner, "夜", knowledge=active_food_knowledge)
    snacks_detail = estimate_calorie_detail(snacks, "間食", knowledge=active_food_knowledge)
    drinks_detail = estimate_calorie_detail(work_drinks, "仕事中のドリンク", knowledge=active_food_knowledge)
    legacy_capture_items = [
        *legacy_meal_capture_items(breakfast, breakfast_detail, "breakfast", breakfast_kcal_manual),
        *legacy_meal_capture_items(lunch, lunch_detail, "lunch", lunch_kcal_manual),
        *legacy_meal_capture_items(dinner, dinner_detail, "dinner", dinner_kcal_manual),
        *legacy_meal_capture_items(snacks, snacks_detail, "snacks", snacks_kcal_manual),
        *legacy_meal_capture_items(work_drinks, drinks_detail, "drinks", drinks_kcal_manual),
    ]
    all_capture_items = [*smart_capture_items, *legacy_capture_items]
    daily_builder = canonical_builder_result(
        {
            "date": record_date.isoformat(),
            "mode": mode,
            "event_name": event_name,
            "weight": weight,
            "sleep_hours": sleep_hours,
            "condition": parse_number(condition, default=None),
            "steps": steps,
            "alcohol_consumed": alcohol == "あり",
            "alcohol_detail": alcohol_detail,
            "alcohol_level": alcohol_level,
            "workout": canonical_workout_from_text(trained, training_detail),
            "notes": comment,
        },
        all_capture_items,
    )
    with st.expander("Generated Canonical Schema 1.0", expanded=False):
        if daily_builder["validation_passed"] and not daily_builder["normalization_changes"]:
            st.success("Validation: PASS / Compatibility normalization: 0 changes")
        else:
            st.error("Canonical validation failed. 保存は実行できません。")
            for issue in daily_builder["validation_issues"]:
                st.write(f"- {issue.get('path', '$')}: {issue.get('message', 'Validation error')}")
        st.code(json.dumps(daily_builder["canonical"], ensure_ascii=False, indent=2), language="json")

    submitted = st.form_submit_button(
        "CSVに保存する",
        disabled=not daily_builder["validation_passed"] or bool(daily_builder["normalization_changes"]),
    )

if submitted:
    canonical_record = daily_builder["canonical"]
    resolved_daily_nutrition = resolve_record_nutrition(
        canonical_record,
        lambda text, meal_type: resolve_food_text(text, meal_type, knowledge=active_food_knowledge),
    )
    canonical_projection = canonical_to_projection(canonical_record, resolved_daily_nutrition)
    breakfast_kcal = canonical_projection.get("朝カロリー(kcal)")
    lunch_kcal = canonical_projection.get("昼カロリー(kcal)")
    dinner_kcal = canonical_projection.get("夜カロリー(kcal)")
    snacks_kcal = canonical_projection.get("間食カロリー(kcal)")
    drinks_kcal = canonical_projection.get("ドリンクカロリー(kcal)")
    calorie_total = resolved_daily_nutrition["totals"].get("calories_kcal")
    estimated_calories = int(round(calorie_total)) if calorie_total is not None else None
    consumed_sources = {
        str(item.get("source_type") or "unknown")
        for item in all_capture_items
        if float(item.get("consumed_quantity") or 0) > 0
    }
    calorie_confidence = (
        "low"
        if consumed_sources & {"estimated", "unknown"}
        else "medium"
        if "trusted_catalog" in consumed_sources
        else "high"
        if consumed_sources
        else "low"
    )

    record = fill_body_scores(
        {
            **canonical_projection,
            "日付": pd.to_datetime(record_date),
            "モード": mode,
            "イベント名": event_name,
            "体重": weight,
            "歩数": steps,
            "歩数ランク": rank_steps(steps),
            "睡眠時間": sleep_hours,
            "朝": canonical_projection.get("朝", ""),
            "昼": canonical_projection.get("昼", ""),
            "夜": canonical_projection.get("夜", ""),
            "間食": canonical_projection.get("間食", ""),
            "仕事中のドリンク": canonical_projection.get("仕事中のドリンク", ""),
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
            "タンパク質(g)": resolved_daily_nutrition["totals"].get("protein_g"),
            "脂質(g)": resolved_daily_nutrition["totals"].get("fat_g"),
            "炭水化物(g)": resolved_daily_nutrition["totals"].get("carbs_g"),
            "カロリー不明件数": resolved_daily_nutrition.get("unknown_calorie_count", 0),
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
                    ("朝", canonical_projection.get("朝", ""), {}),
                    ("昼", canonical_projection.get("昼", ""), {}),
                    ("夜", canonical_projection.get("夜", ""), {}),
                    ("間食", canonical_projection.get("間食", ""), {}),
                    ("仕事中のドリンク", canonical_projection.get("仕事中のドリンク", ""), {}),
                ],
                record_date=record_date.isoformat(),
                operation_id=f"manual-save:{record_date.isoformat()}",
                used_at=pd.to_datetime(record_date).isoformat(),
                knowledge=active_food_knowledge,
            )
        except Exception as exc:
            food_summary = empty_food_resolution_summary()
            st.warning(f"CSVは保存しましたが、Personal Food Masterの記録に失敗しました: {exc}")
        calorie_message = (
            f"既知カロリーは{estimated_calories:,}kcal"
            if estimated_calories is not None
            else "カロリーは不明"
        )
        st.success(f"CSVへ保存しました。{calorie_message}、Body Scoreは{record['Body Score']}点です。")
        meal_calorie_display = lambda value: f"{int(round(value)):,}kcal" if value is not None else "—"
        st.write(
            f"朝 {meal_calorie_display(breakfast_kcal)} / 昼 {meal_calorie_display(lunch_kcal)} / "
            f"夜 {meal_calorie_display(dinner_kcal)} / 間食 {meal_calorie_display(snacks_kcal)} / "
            f"ドリンク {meal_calorie_display(drinks_kcal)}"
        )
        st.write(f"カロリー推定信頼度: {calorie_confidence}")
        if food_summary["encounter_count"]:
            st.caption(f"Personal Food Masterに{food_summary['encounter_count']}件の食品遭遇を記録しました。")
        render_food_import_summary(food_summary)
        st.session_state[CAPTURE_STATE_KEY] = []
    except Exception as exc:
        st.error(f"保存に失敗しました: {exc}")

st.header("BodyOS JSON Import")
st.caption("正式Schema 1.0または旧BodyOS JSONを検証し、保存内容を確認してからrecords.csvへ反映します。")
with st.expander("Canonical Schema 1.0 Example / JSON作成ガイド", expanded=False):
    st.caption("このExampleはSchema 1.0だけで構成された、コピー用の正式入力例です。")
    st.code(json.dumps(load_canonical_example(), ensure_ascii=False, indent=2), language="json")
    st.markdown(
        "[JSON Authoring Guide](https://github.com/ZOEykyk/body-recomp-dashboard/blob/main/docs/bodyos-json-authoring-guide.md) / "
        "[Schema file](https://github.com/ZOEykyk/body-recomp-dashboard/blob/main/schemas/bodyos-daily-log.schema.json)"
    )
chatgpt_log = st.text_area(
    "JSON形式のログ",
    placeholder='{"schema_version":"1.0","date":"2026-08-09","sleep":{"hours":7.5},"condition":8,"steps":9000,"meals":{"breakfast":[],"lunch":[],"dinner":[],"snacks":[],"drinks":[]}}',
    height=220,
)
import_state = streamlit_session_state()

if st.button("取り込み内容を確認"):
    for key in (
        "bodyos_import_document",
        "bodyos_import_preview",
        "bodyos_import_preview_fingerprint",
        "bodyos_import_result",
    ):
        import_state.pop(key, None)
    try:
        document = parse_import_json(chatgpt_log)
        existing_dates = set(pd.to_datetime(df["日付"], errors="coerce").dt.strftime("%Y-%m-%d").dropna())
        preview = preview_import(document, existing_dates)
        import_state["bodyos_import_document"] = document
        import_state["bodyos_import_preview"] = preview
        import_state["bodyos_import_preview_fingerprint"] = import_document_fingerprint(document)
    except BodyOSImportValidationError as exc:
        render_schema_validation_errors(exc)
        if exc.normalization_changes:
            with st.expander("Validation前に適用可能だったCompatibility normalization", expanded=False):
                render_normalization_report(exc.normalization_changes)
        if exc.warnings:
            with st.expander("変換時の警告"):
                for message in exc.warnings:
                    st.write(f"- {message}")
    except Exception as exc:
        LOGGER.exception("Import preview failed")
        st.error("取り込み内容を確認できませんでした。JSON形式と日付を確認してください。")
        with st.expander("開発者向け詳細"):
            st.code(f"{type(exc).__name__}: {exc}")

import_document = import_state.get("bodyos_import_document")
import_preview = import_state.get("bodyos_import_preview")
preview_fingerprint = import_state.get("bodyos_import_preview_fingerprint")
preview_is_current = False
if isinstance(import_document, dict) and isinstance(import_preview, dict) and str(chatgpt_log or "").strip():
    try:
        current_document = parse_import_json(chatgpt_log)
        preview_is_current = (
            import_document_fingerprint(current_document) == preview_fingerprint
            and import_document_fingerprint(import_document) == preview_fingerprint
        )
    except BodyOSImportValidationError:
        preview_is_current = False
if isinstance(import_document, dict) and isinstance(import_preview, dict) and not preview_is_current:
    import_state.pop("bodyos_import_result", None)
    st.info("JSONがPreview後に変更されています。現在の内容をもう一度確認してください。")
    import_document = None
    import_preview = None

if isinstance(import_document, dict) and isinstance(import_preview, dict):
    st.subheader("Import Preview")
    normalization = import_document.get("metadata", {}).get("normalization", {})
    render_normalization_report(normalization.get("changes") or [])
    st.success("Schema Validation OK。保存対象はCanonical Schema 1.0です。")
    with st.expander("保存されるCanonical JSON", expanded=False):
        st.code(
            json.dumps(canonical_document_payload(import_document), ensure_ascii=False, indent=2),
            language="json",
        )
    preview_rows = pd.DataFrame(import_preview["records"]).rename(
        columns={
            "date": "対象日",
            "weight": "体重",
            "sleep_hours": "睡眠",
            "condition": "体調",
            "steps": "歩数",
            "meal_items": "食事件数",
            "session_count": "セッション",
            "exercise_count": "種目",
            "set_count": "セット",
            "duration_minutes": "時間(分)",
            "conflict": "既存日",
            "warning_count": "警告",
        }
    )
    st.dataframe(preview_rows, use_container_width=True, hide_index=True)
    st.caption(
        f"日次 {import_preview['record_count']}件 / 食品 {import_preview['meal_item_count']}件 / "
        f"筋トレ {import_preview['workout_session_count']}セッション / "
        f"種目 {import_preview['exercise_count']}件 / セット {import_preview['set_count']}件"
    )
    if import_preview["warnings"]:
        st.warning(f"{len(import_preview['warnings'])}件の確認事項があります。保存は禁止せず、内容確認を推奨します。")
        with st.expander("警告を確認"):
            for message in import_preview["warnings"]:
                st.write(f"- {message}")

    conflict_label = st.radio(
        "同じ日付が保存済みの場合",
        ["更新（入力されたセクションのみ）", "置換（1日分を入れ替え）", "中止（保存済みの日をスキップ）"],
        index=0,
        horizontal=True,
    )
    conflict_policy = {
        "更新（入力されたセクションのみ）": "update",
        "置換（1日分を入れ替え）": "replace",
        "中止（保存済みの日をスキップ）": "cancel",
    }[conflict_label]

    if st.button("確認した内容を保存", type="primary"):
        started_at = time.monotonic()
        operation_id = operation_import_id()
        try:
            projected_rows, import_diagnostics = build_import_rows(
                import_document,
                food_knowledge=active_food_knowledge,
            )
            existing_dates = set(pd.to_datetime(df["日付"], errors="coerce").dt.strftime("%Y-%m-%d").dropna())
            updated_data, save_counts = apply_import_rows(
                df,
                projected_rows,
                import_diagnostics,
                conflict_policy,
            )
            save_data(updated_data)
            df = updated_data

            food_summary = empty_food_resolution_summary()
            try:
                for canonical_record, imported_record in zip(import_document["records"], projected_rows):
                    if conflict_policy == "cancel" and canonical_record["date"] in existing_dates:
                        continue
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
                        record_date=canonical_record["date"],
                        operation_id=f"json-import:{imported_record['Import ID']}",
                        used_at=f"{canonical_record['date']}T00:00:00",
                        knowledge=active_food_knowledge,
                    )
                    merge_food_resolution_summary(food_summary, imported_summary)
            except Exception as exc:
                food_summary["save_failed"] += 1
                LOGGER.warning("Food Knowledge persistence failed after daily save: %s", type(exc).__name__)

            unknown_count = sum(item["unknown_calorie_count"] for item in import_diagnostics)
            result = {
                **save_counts,
                "daily_count": len(projected_rows) - save_counts["skipped"],
                "meal_item_count": import_preview["meal_item_count"],
                "workout_session_count": import_preview["workout_session_count"],
                "exercise_count": import_preview["exercise_count"],
                "set_count": import_preview["set_count"],
                "unknown_calorie_count": unknown_count,
                "food_summary": food_summary,
            }
            import_state["bodyos_import_result"] = result
            LOGGER.info(
                json.dumps(
                    structured_import_log(
                        import_id=operation_id,
                        user_id=PERSONAL_FOOD_USER_ID,
                        records=import_document["records"],
                        warning_count=len(import_preview["warnings"]) + unknown_count,
                        section="complete",
                        started_at=started_at,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            st.rerun()
        except Exception as exc:
            LOGGER.exception(
                json.dumps(
                    structured_import_log(
                        import_id=operation_id,
                        user_id=PERSONAL_FOOD_USER_ID,
                        records=import_document.get("records") or [],
                        warning_count=len(import_preview.get("warnings") or []),
                        section="save",
                        started_at=started_at,
                        error_location=type(exc).__name__,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            st.error("保存できませんでした。records.csvへの反映は完了していません。")
            with st.expander("開発者向け詳細"):
                st.code(f"{type(exc).__name__}: {exc}")

import_result = import_state.get("bodyos_import_result")
if isinstance(import_result, dict):
    st.success(
        f"日次 {import_result['daily_count']}件を保存しました。"
        f"追加 {import_result['added']}件 / 更新 {import_result['updated']}件 / "
        f"置換 {import_result['replaced']}件 / スキップ {import_result['skipped']}件"
    )
    st.write(
        f"✓ 日次基本情報 {import_result['daily_count']}件  \n"
        f"✓ 食品 {import_result['meal_item_count']}件  \n"
        f"✓ 筋トレ {import_result['workout_session_count']}セッション  \n"
        f"✓ 種目 {import_result['exercise_count']}件  \n"
        f"✓ セット {import_result['set_count']}件"
    )
    if import_result["unknown_calorie_count"]:
        st.warning(f"カロリー不明 {import_result['unknown_calorie_count']}件。既知分だけを合計しています。")
    render_food_import_summary(import_result["food_summary"])

if not df.empty:
    st.subheader("BodyOS JSON Export")
    export_dates = pd.to_datetime(df["日付"], errors="coerce").dropna().dt.strftime("%Y-%m-%d").tolist()
    export_date = st.selectbox("エクスポート対象日", export_dates, index=max(len(export_dates) - 1, 0))
    export_match = df[pd.to_datetime(df["日付"], errors="coerce").dt.strftime("%Y-%m-%d") == export_date]
    if not export_match.empty:
        export_payload = export_projection(export_match.iloc[-1].to_dict())
        st.download_button(
            "正式Schema 1.0 JSONをダウンロード",
            json.dumps(export_payload, ensure_ascii=False, indent=2),
            file_name=f"bodyos-{export_date}.json",
            mime="application/json",
        )

if not df.empty:
    st.header("メンテナンス")
    if st.button("Body Scoreを再計算"):
        try:
            df = recalculate_body_scores(df)
            save_data(df)
            st.success("全レコードのBody Scoreと内訳スコアを最新ロジックで再計算しました。")
        except Exception as exc:
            st.error(f"Body Scoreの再計算に失敗しました: {exc}")

show_food_knowledge_tools = st.toggle("Food Knowledge詳細を表示", value=False)
if show_food_knowledge_tools:
    render_food_knowledge_dashboard(PERSONAL_FOOD_REPOSITORY, PERSONAL_FOOD_USER_ID)
    render_food_master_management(PERSONAL_FOOD_REPOSITORY, PERSONAL_FOOD_USER_ID)
    render_food_knowledge_debug_panel()

if performance_debug_enabled():
    with st.expander("Performance Debug", expanded=False):
        st.dataframe(pd.DataFrame(PERFORMANCE.summary()), use_container_width=True, hide_index=True)

st.caption("注意: カロリーは概算です。正確にしたい日は手入力欄を使ってください。")
