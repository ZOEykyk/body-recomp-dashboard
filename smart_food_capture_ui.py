from __future__ import annotations

from copy import deepcopy
import html
from typing import Any, Callable

import streamlit as st

from food_master_repository import FoodMasterRepository
from food_knowledge_diagnostics import (
    confirmed_save_diagnostics,
    food_knowledge_user_key,
)
from image_preprocessing import MAX_IMAGE_BYTES
from label_ocr_runtime import LabelOcrError, capture_label_image, image_sha256
from ocr_runtime_diagnostics import ocr_runtime_metadata_diagnostics
from personal_food_master import confirm_capture_food
from smart_food_capture import (
    MEAL_LABELS,
    calculate_daily_nutrition,
    capture_editor_nutrition_basis,
    prepare_food_candidate_editor_result,
    search_food_candidates_with_diagnostics,
    source_presentation,
    unknown_candidate,
)


CAPTURE_STATE_KEY = "bodyos_smart_food_capture_items"
FOOD_KNOWLEDGE_LAST_SAVE_DEBUG_KEY = "bodyos_food_knowledge_last_save_debug"
FOOD_KNOWLEDGE_RUNTIME_DEBUG_KEY = "bodyos_food_knowledge_runtime_debug"
FOOD_KNOWLEDGE_SEARCH_DEBUG_KEY = "bodyos_food_knowledge_search_debug"
LABEL_OCR_CANDIDATE_KEY = "bodyos_label_ocr_candidate"
LABEL_OCR_METRICS_KEY = "bodyos_label_ocr_metrics"
SOURCE_MODE_OPTIONS = {
    "候補の値を使用": "candidate",
    "商品ラベルで確認": "user_label",
    "概算値として入力": "estimated",
}
UNIT_OPTIONS = ["", "個", "本", "袋", "パック", "缶", "杯", "食", "人前", "g", "ml"]
BASIS_OPTIONS = ["per_item", "per_package", "per_serving", "per_100g", "per_100ml", "total", "unknown"]


def _nutrition_input(label: str, value: Any, key: str) -> float | None:
    numeric = float(value) if isinstance(value, (int, float)) else None
    return st.number_input(label, min_value=0.0, value=numeric, step=0.1, key=key)


def _nutrition_basis_input(
    nutrition: dict[str, Any],
    unit: Any,
    key: str,
    *,
    preserve_unknown: bool = False,
) -> str:
    basis_value = capture_editor_nutrition_basis(
        nutrition,
        unit,
        preserve_unknown=preserve_unknown,
    )
    if key in st.session_state and st.session_state.get(key) == "unknown" and not preserve_unknown:
        # Synchronize stale pre-fix widget state before this run creates the widget.
        st.session_state[key] = basis_value
    return st.selectbox(
        "栄養値の基準",
        BASIS_OPTIONS,
        index=BASIS_OPTIONS.index(basis_value),
        key=key,
    )


def _source_mode_default(candidate: dict[str, Any], nutrition: dict[str, Any]) -> str:
    if candidate.get("source_type") == "user_label":
        return "商品ラベルで確認"
    if candidate.get("source_type") == "estimated":
        return "概算値として入力"
    capture_metadata = candidate.get("capture_metadata")
    capture_channel = capture_metadata.get("capture_channel") if isinstance(capture_metadata, dict) else None
    has_nutrition = any(nutrition.get(field) is not None for field in ("calories_kcal", "protein_g", "fat_g", "carbs_g"))
    if capture_channel == "label_ocr" and has_nutrition:
        # Selecting this default does not persist anything. The add/confirm action is the trust boundary.
        return "商品ラベルで確認"
    if candidate.get("source_type") == "unknown" and has_nutrition:
        return "概算値として入力"
    return "候補の値を使用"


def render_food_candidate_editor(
    candidate: dict[str, Any],
    *,
    key_prefix: str,
    include_remember: bool = False,
) -> dict[str, Any]:
    """Render one reusable editor for search, OCR, barcode, and existing candidates."""
    capture_metadata = candidate.get("capture_metadata")
    is_unconfirmed_ocr = (
        isinstance(capture_metadata, dict)
        and capture_metadata.get("capture_channel") == "label_ocr"
        and not candidate.get("confirmed")
    )
    warnings = capture_metadata.get("warnings") if isinstance(capture_metadata, dict) else []
    if warnings:
        st.warning("抽出結果を確認してください: " + " / ".join(str(item.get("message") or item.get("code")) for item in warnings[:3]))

    name = st.text_input("食品名", value=str(candidate.get("display_name") or ""), key=f"{key_prefix}-name")
    meal_type_value = str(candidate.get("meal_type") or "snacks")
    meal_type = st.selectbox(
        "食事区分",
        list(MEAL_LABELS),
        index=list(MEAL_LABELS).index(meal_type_value) if meal_type_value in MEAL_LABELS else 3,
        format_func=lambda value: MEAL_LABELS[value],
        key=f"{key_prefix}-meal",
    )
    quantity = st.number_input(
        "購入・用意した数量",
        min_value=0.1,
        value=float(candidate.get("quantity") or 1),
        step=0.1,
        key=f"{key_prefix}-quantity",
    )
    unit_value = str(candidate.get("unit") or "")
    unit = st.selectbox(
        "単位",
        UNIT_OPTIONS,
        index=UNIT_OPTIONS.index(unit_value) if unit_value in UNIT_OPTIONS else 0,
        key=f"{key_prefix}-unit",
    )
    default_consumed = (
        float(candidate.get("consumed_quantity") or 0)
        if "consumed_quantity" in candidate
        else float(quantity)
    )
    consumed_quantity = st.number_input(
        "摂取した数量",
        min_value=0.0,
        max_value=float(quantity),
        value=min(default_consumed, float(quantity)),
        step=0.1,
        help="0なら購入・予定として保持され、Daily nutritionへ加算されません。",
        key=f"{key_prefix}-consumed",
    )
    nutrition = deepcopy(candidate.get("nutrition") or {})
    calories = _nutrition_input("1単位あたり Calories", nutrition.get("calories_kcal"), f"{key_prefix}-kcal")
    protein = _nutrition_input("1単位あたり Protein", nutrition.get("protein_g"), f"{key_prefix}-p")
    fat = _nutrition_input("1単位あたり Fat", nutrition.get("fat_g"), f"{key_prefix}-f")
    carbs = _nutrition_input("1単位あたり Carbs", nutrition.get("carbs_g"), f"{key_prefix}-c")
    basis = _nutrition_basis_input(
        nutrition,
        unit,
        f"{key_prefix}-basis",
        preserve_unknown=is_unconfirmed_ocr,
    )
    source_default = _source_mode_default(candidate, nutrition)
    source_label = st.radio(
        "栄養値の由来",
        list(SOURCE_MODE_OPTIONS),
        index=list(SOURCE_MODE_OPTIONS).index(source_default),
        horizontal=True,
        key=f"{key_prefix}-source",
    )
    notes = st.text_input(
        "備考",
        value=str(candidate.get("notes") or ""),
        key=f"{key_prefix}-notes",
    )
    remember = (
        st.checkbox("この食品の栄養値を今後も使用する", key=f"{key_prefix}-remember")
        if include_remember
        else False
    )
    return {
        "name": name,
        "meal_type": meal_type,
        "quantity": quantity,
        "unit": unit,
        "consumed_quantity": consumed_quantity,
        "nutrition": {
            "basis": basis,
            "calories_kcal": calories,
            "protein_g": protein,
            "fat_g": fat,
            "carbs_g": carbs,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        },
        "source_mode": SOURCE_MODE_OPTIONS[source_label],
        "notes": notes,
        "remember": remember,
    }


def _source_badge(item: dict[str, Any]) -> str:
    source_type = str(item.get("source_type") or "unknown")
    presentation = source_presentation(source_type)
    css_class = "confirmed" if presentation["label"] == "確定" else "estimated" if presentation["label"] == "推定" else "unknown"
    return (
        f"<span class='bodyos-capture-badge {css_class}'>{html.escape(presentation['label'])}</span>"
        f"<span class='bodyos-capture-source'>{html.escape(presentation['detail'])} / {html.escape(presentation['confidence'].title())}</span>"
    )


def _render_styles() -> None:
    st.markdown(
        """
        <style>
          .bodyos-smart-capture, .bodyos-smart-capture * { box-sizing: border-box; min-width: 0; }
          .bodyos-capture-summary {
            border: 1px solid rgba(49, 51, 63, 0.18); border-radius: 8px;
            padding: 0.8rem; margin: 0.45rem 0; overflow-wrap: anywhere;
          }
          .bodyos-capture-summary.planned { border-style: dashed; opacity: 0.82; }
          .bodyos-capture-name { font-weight: 700; color: #20242c; }
          .bodyos-capture-meta { margin-top: 0.35rem; color: #4b5563; line-height: 1.45; }
          .bodyos-capture-badge {
            display: inline-block; border-radius: 999px; padding: 0.12rem 0.48rem;
            margin-right: 0.4rem; font-size: 0.78rem; font-weight: 700;
          }
          .bodyos-capture-badge.confirmed { background: #dff5e8; color: #17633a; }
          .bodyos-capture-badge.estimated { background: #fff0cc; color: #7a4b00; }
          .bodyos-capture-badge.unknown { background: #f1f2f4; color: #4b5563; }
          .bodyos-capture-source { font-size: 0.86rem; color: #4b5563; overflow-wrap: anywhere; }
          .bodyos-capture-totals {
            display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.55rem;
            margin: 0.65rem 0;
          }
          .bodyos-capture-total { border-left: 4px solid #1683d8; padding: 0.55rem 0.65rem; background: #f6f9fc; }
          .bodyos-capture-total strong { display: block; color: #20242c; font-size: 1.12rem; }
          .bodyos-capture-total span { color: #5b6472; font-size: 0.78rem; }
          @media (max-width: 640px) {
            .bodyos-capture-totals { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .bodyos-capture-summary { padding: 0.7rem; }
          }
        </style>
        <div class="bodyos-smart-capture"></div>
        """,
        unsafe_allow_html=True,
    )


def _format_value(value: Any, suffix: str) -> str:
    if value is None:
        return "—"
    number = float(value)
    rendered = f"{number:,.1f}".rstrip("0").rstrip(".")
    return f"{rendered}{suffix}"


def _render_totals(items: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = calculate_daily_nutrition(items)
    totals = aggregate["totals"]
    cards = [
        ("Calories", _format_value(totals["calories_kcal"], " kcal")),
        ("Protein", _format_value(totals["protein_g"], " g")),
        ("Fat", _format_value(totals["fat_g"], " g")),
        ("Carbs", _format_value(totals["carbs_g"], " g")),
    ]
    html_cards = "".join(
        f"<div class='bodyos-capture-total'><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>"
        for label, value in cards
    )
    st.markdown(f"<div class='bodyos-capture-totals'>{html_cards}</div>", unsafe_allow_html=True)
    st.caption(
        f"栄養値確定率 {aggregate['known_coverage_percent']}% / "
        f"摂取済み {aggregate['consumed_count']}件 / 不明 {aggregate['unknown_count']}件"
    )
    if aggregate["unknown_items"]:
        st.warning("カロリー不明: " + "、".join(aggregate["unknown_items"]))
    return aggregate


def render_food_knowledge_debug_panel() -> None:
    """Render the latest save/search diagnostics inside Food Knowledge details."""
    session_state = getattr(st, "session_state", {})
    runtime = deepcopy(session_state.get(FOOD_KNOWLEDGE_RUNTIME_DEBUG_KEY) or {})
    last_save = deepcopy(session_state.get(FOOD_KNOWLEDGE_LAST_SAVE_DEBUG_KEY))
    search = deepcopy(session_state.get(FOOD_KNOWLEDGE_SEARCH_DEBUG_KEY) or {})
    try:
        ocr_runtime = ocr_runtime_metadata_diagnostics()
    except Exception as exc:
        ocr_runtime = {
            "diagnostics_version": "unavailable",
            "probe_status": "error",
            "probe_error_type": type(exc).__name__,
        }
    revision = str(runtime.get("source_revision") or "unavailable")
    version = str(runtime.get("diagnostics_version") or "unavailable")
    st.markdown("### Food Knowledge Diagnostics")
    st.caption(f"Diagnostics {version} / Source revision `{revision}`")
    st.caption("Secrets、画像、OCR原文、食品名、栄養値は表示しません。runtimeと保存経路のメタデータのみです。")
    with st.expander("Food Knowledge Debug", expanded=True):
        st.json(
            {
                "runtime": runtime,
                "ocr_runtime": ocr_runtime,
                "last_confirmed_save": last_save,
                "current_search": search,
            },
            expanded=True,
        )


def _render_capture_card(item: dict[str, Any], index: int, items: list[dict[str, Any]]) -> None:
    consumed = float(item.get("consumed_quantity") or 0)
    quantity = float(item.get("quantity") or 1)
    status = str(item.get("consumption_status") or "planned")
    status_label = {
        "planned": "購入・予定（集計外）",
        "partially_consumed": f"{consumed:g}/{quantity:g} 摂取",
        "consumed": "摂取済み",
    }.get(status, status)
    card_class = "planned" if consumed <= 0 else ""
    st.markdown(
        "<div class='bodyos-capture-summary " + card_class + "'>"
        f"<div class='bodyos-capture-name'>{html.escape(str(item.get('display_name') or '名称未設定'))}</div>"
        f"<div class='bodyos-capture-meta'>{html.escape(MEAL_LABELS.get(str(item.get('meal_type')), '間食'))} / "
        f"購入 {quantity:g}{html.escape(str(item.get('unit') or ''))} / {html.escape(status_label)}</div>"
        f"<div class='bodyos-capture-meta'>{_source_badge(item)}</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    capture_id = str(item.get("capture_id") or index)
    with st.expander("編集", expanded=False):
        editor_values = render_food_candidate_editor(
            item,
            key_prefix=f"capture-{capture_id}",
        )
        action_col1, action_col2 = st.columns(2)
        if action_col1.button("更新", key=f"capture-update-{capture_id}", width="stretch"):
            try:
                items[index] = prepare_food_candidate_editor_result(
                    item,
                    editor_values,
                    capture_id=capture_id,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state[CAPTURE_STATE_KEY] = items
                st.rerun()
        if action_col2.button("削除", key=f"capture-delete-{capture_id}", width="stretch"):
            st.session_state[CAPTURE_STATE_KEY] = [value for position, value in enumerate(items) if position != index]
            st.rerun()


def _confirmed_editor_item(
    candidate: dict[str, Any],
    editor_values: dict[str, Any],
    repository: FoodMasterRepository,
    user_id: str,
    *,
    on_food_knowledge_changed: Callable[[], None] | None,
) -> dict[str, Any]:
    prepared = prepare_food_candidate_editor_result(candidate, editor_values)
    if not editor_values.get("remember"):
        return prepared
    if prepared["source_type"] != "user_label":
        raise ValueError("今後も使う値は「商品ラベルで確認」を選択してください。概算値は確定保存しません。")
    revision_before = repository.cache_revision()
    stored = confirm_capture_food(repository, user_id, prepared)
    prepared["food_id"] = stored.get("food_id")
    prepared["source_detail"] = "過去の確認値"
    st.session_state[FOOD_KNOWLEDGE_LAST_SAVE_DEBUG_KEY] = confirmed_save_diagnostics(
        repository,
        user_id,
        stored,
        revision_before=revision_before,
    )
    if on_food_knowledge_changed is not None:
        on_food_knowledge_changed()
    return prepared


def _render_label_capture(
    items: list[dict[str, Any]],
    repository: FoodMasterRepository,
    user_id: str,
    *,
    on_food_knowledge_changed: Callable[[], None] | None,
) -> None:
    with st.expander("栄養ラベル画像から追加", expanded=False):
        st.caption("カメラ撮影またはJPG/JPEG/PNG・最大10MB。画像とOCR原文は保存されません。結果を確認・修正してください。")
        input_method = st.radio(
            "画像の入力方法",
            ("カメラで撮影", "画像をUpload"),
            horizontal=True,
            key="label-ocr-input-method",
        )
        if input_method == "カメラで撮影":
            selected_image = st.camera_input(
                "栄養ラベルを撮影",
                key="label-ocr-camera",
            )
            preview_caption = "撮影画像"
        else:
            selected_image = st.file_uploader(
                "栄養ラベル画像",
                type=["jpg", "jpeg", "png"],
                key="label-ocr-upload",
            )
            preview_caption = "アップロード画像"
        suggested_name = st.text_input(
            "食品名（任意）",
            placeholder="例：商品名や味",
            key="label-ocr-name",
        )
        current_hash = None
        image_bytes = None
        if selected_image is not None:
            image_bytes = selected_image.getvalue()
            if len(image_bytes) > MAX_IMAGE_BYTES:
                st.error("画像は10MB以下にしてください。")
                image_bytes = None
            else:
                current_hash = image_sha256(image_bytes)
                try:
                    st.image(image_bytes, caption=preview_caption, width="stretch")
                except Exception:
                    st.warning("画像を表示できません。別のJPG/JPEG/PNGを選ぶか、手入力で続けてください。")
            action_ocr, action_manual = st.columns(2)
            if action_ocr.button(
                "OCRを実行",
                type="primary",
                key="label-ocr-run",
                width="stretch",
                disabled=image_bytes is None,
            ):
                try:
                    result = capture_label_image(image_bytes, suggested_name=suggested_name)
                except LabelOcrError as exc:
                    st.session_state[LABEL_OCR_CANDIDATE_KEY] = unknown_candidate(
                        suggested_name or "ラベルから追加した食品"
                    )
                    st.session_state[LABEL_OCR_METRICS_KEY] = {"status": "failed"}
                    st.warning(f"{exc} 読み取れなかったので手入力で続けてください。")
                except Exception:
                    st.session_state[LABEL_OCR_CANDIDATE_KEY] = unknown_candidate(
                        suggested_name or "ラベルから追加した食品"
                    )
                    st.session_state[LABEL_OCR_METRICS_KEY] = {"status": "failed"}
                    st.warning("OCRを実行できませんでした。手入力で続けてください。")
                else:
                    st.session_state[LABEL_OCR_CANDIDATE_KEY] = result["candidate"]
                    st.session_state[LABEL_OCR_METRICS_KEY] = {
                        "status": "completed",
                        **result["metrics"],
                    }
            if action_manual.button("手入力で続ける", key="label-ocr-manual", width="stretch"):
                st.session_state[LABEL_OCR_CANDIDATE_KEY] = unknown_candidate(
                    suggested_name or "ラベルから追加した食品"
                )
                st.session_state[LABEL_OCR_METRICS_KEY] = {"status": "manual"}

        candidate = deepcopy(st.session_state.get(LABEL_OCR_CANDIDATE_KEY))
        if isinstance(candidate, dict):
            metadata = candidate.get("capture_metadata")
            candidate_hash = metadata.get("image_sha256") if isinstance(metadata, dict) else None
            if candidate_hash and candidate_hash != current_hash:
                candidate = None
        if not isinstance(candidate, dict):
            return

        metrics = deepcopy(st.session_state.get(LABEL_OCR_METRICS_KEY) or {})
        if metrics.get("status") == "completed":
            detected = int(metrics.get("candidate_fields") or 0)
            cache_label = "cache hit" if metrics.get("cache_hit") else "OCR実行"
            if detected == 0:
                st.warning("栄養値を読み取れなかったので、手入力で続けてください。")
            elif detected < 4:
                st.warning(f"OCR結果は主要栄養項目 {detected}/4です。不足項目を確認・修正してください。")
            else:
                st.success(f"OCR完了: 主要栄養項目 4/4・{cache_label}")
            st.caption(
                f"前処理 {float(metrics.get('preprocessing_ms') or 0):,.0f}ms / "
                f"OCR {float(metrics.get('ocr_ms') or 0):,.0f}ms / "
                f"候補生成 {float(metrics.get('candidate_ms') or 0):,.1f}ms"
            )
        st.markdown(_source_badge(candidate), unsafe_allow_html=True)
        editor_values = render_food_candidate_editor(
            candidate,
            key_prefix=f"label-{candidate['candidate_id']}",
            include_remember=True,
        )
        if st.button("確認して食品へ追加", type="primary", key=f"label-add-{candidate['candidate_id']}"):
            try:
                prepared = _confirmed_editor_item(
                    candidate,
                    editor_values,
                    repository,
                    user_id,
                    on_food_knowledge_changed=on_food_knowledge_changed,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                items.append(prepared)
                st.session_state[CAPTURE_STATE_KEY] = items
                st.session_state.pop(LABEL_OCR_CANDIDATE_KEY, None)
                st.session_state.pop(LABEL_OCR_METRICS_KEY, None)
                st.rerun()


def render_smart_food_capture(
    repository: FoodMasterRepository,
    user_id: str,
    knowledge: dict[str, Any],
    *,
    on_food_knowledge_changed: Callable[[], None] | None = None,
    runtime_diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Render the low-friction food workflow and return a copied capture state."""
    session_state = getattr(st, "session_state", None)
    if not hasattr(session_state, "get") or not hasattr(session_state, "__setitem__"):
        # Older validation scripts import app.py with a minimal Streamlit stub.
        return []
    _render_styles()
    st.subheader("Smart Food Capture")
    st.caption("食品を検索して候補を確認します。購入・予定は摂取するまで栄養集計へ入りません。")
    items = deepcopy(session_state.get(CAPTURE_STATE_KEY) or [])
    _render_label_capture(
        items,
        repository,
        user_id,
        on_food_knowledge_changed=on_food_knowledge_changed,
    )

    query = st.text_input("食品を検索", placeholder="例：SAVAS BIO、理想のトマト、みたらし団子", key="smart-food-query")
    suggestions, search_diagnostics = search_food_candidates_with_diagnostics(query, knowledge)
    runtime = deepcopy(runtime_diagnostics or {})
    search_user_key = food_knowledge_user_key(user_id)
    last_save_diagnostics = deepcopy(session_state.get(FOOD_KNOWLEDGE_LAST_SAVE_DEBUG_KEY))
    search_diagnostics.update(
        {
            "search_user_key": search_user_key,
            "runtime_user_matches_search": runtime.get("user_key") == search_user_key,
            "last_save_user_matches_search": (
                last_save_diagnostics.get("save_user_key") == search_user_key
                if isinstance(last_save_diagnostics, dict)
                else None
            ),
            "repository_cache_revision": repository.cache_revision(),
            "personal_candidate_food_ids": [
                str(candidate.get("food_id") or "")
                for candidate in suggestions
                if candidate.get("source_type") == "personal_master"
            ],
        }
    )
    session_state[FOOD_KNOWLEDGE_RUNTIME_DEBUG_KEY] = runtime
    session_state[FOOD_KNOWLEDGE_SEARCH_DEBUG_KEY] = deepcopy(search_diagnostics)
    if suggestions:
        options = [candidate["candidate_id"] for candidate in suggestions]
        by_id = {candidate["candidate_id"]: candidate for candidate in suggestions}
        selected_id = st.selectbox(
            "候補",
            options,
            format_func=lambda value: (
                f"{by_id[value]['display_name']} | {by_id[value]['source_detail']}"
            ),
            key="smart-food-suggestion",
        )
        candidate = deepcopy(by_id[selected_id])
    else:
        candidate = unknown_candidate(query) if query.strip() else None

    if candidate is not None:
        st.markdown(_source_badge(candidate), unsafe_allow_html=True)
        editor_key = str(candidate["candidate_id"])
        editor_values = render_food_candidate_editor(
            candidate,
            key_prefix=f"new-{editor_key}",
            include_remember=True,
        )
        if st.button("食品を追加", type="primary", key=f"new-add-{editor_key}"):
            try:
                prepared = _confirmed_editor_item(
                    candidate,
                    editor_values,
                    repository,
                    user_id,
                    on_food_knowledge_changed=on_food_knowledge_changed,
                )
            except ValueError as exc:
                st.error(str(exc))
                return deepcopy(items)
            items.append(prepared)
            st.session_state[CAPTURE_STATE_KEY] = items
            st.rerun()

    st.markdown("#### 今日の食品")
    if not items:
        st.info("食品はまだ追加されていません。従来の自由文入力も引き続き利用できます。")
    for index, item in enumerate(list(items)):
        _render_capture_card(item, index, items)
    _render_totals(items)
    return deepcopy(st.session_state.get(CAPTURE_STATE_KEY) or items)


__all__ = [
    "CAPTURE_STATE_KEY",
    "FOOD_KNOWLEDGE_LAST_SAVE_DEBUG_KEY",
    "FOOD_KNOWLEDGE_RUNTIME_DEBUG_KEY",
    "FOOD_KNOWLEDGE_SEARCH_DEBUG_KEY",
    "LABEL_OCR_CANDIDATE_KEY",
    "LABEL_OCR_METRICS_KEY",
    "render_food_candidate_editor",
    "render_food_knowledge_debug_panel",
    "render_smart_food_capture",
]
