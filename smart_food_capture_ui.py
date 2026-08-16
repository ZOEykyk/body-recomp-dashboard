from __future__ import annotations

from copy import deepcopy
import html
from typing import Any

import streamlit as st

from food_master_repository import FoodMasterRepository
from personal_food_master import confirm_capture_food
from smart_food_capture import (
    MEAL_LABELS,
    calculate_daily_nutrition,
    default_capture_nutrition_basis,
    prepare_capture_item,
    resolve_capture_nutrition_basis,
    search_food_candidates,
    source_presentation,
    unknown_candidate,
)


CAPTURE_STATE_KEY = "bodyos_smart_food_capture_items"
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


def _nutrition_basis_input(nutrition: dict[str, Any], unit: Any, key: str) -> str:
    basis_value = resolve_capture_nutrition_basis(nutrition, unit)["basis"]
    if basis_value == "unknown":
        basis_value = default_capture_nutrition_basis(unit)
    if key in st.session_state and st.session_state.get(key) == "unknown":
        # Synchronize stale pre-fix widget state before this run creates the widget.
        st.session_state[key] = basis_value
    return st.selectbox(
        "栄養値の基準",
        BASIS_OPTIONS,
        index=BASIS_OPTIONS.index(basis_value),
        key=key,
    )


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
        name = st.text_input("食品名", value=str(item.get("display_name") or ""), key=f"capture-name-{capture_id}")
        meal_type = st.selectbox(
            "食事区分",
            list(MEAL_LABELS),
            index=list(MEAL_LABELS).index(str(item.get("meal_type") or "snacks")),
            format_func=lambda value: MEAL_LABELS[value],
            key=f"capture-meal-{capture_id}",
        )
        quantity = st.number_input(
            "購入・用意した数量", min_value=0.1, value=float(item.get("quantity") or 1), step=0.1,
            key=f"capture-quantity-{capture_id}",
        )
        unit_value = str(item.get("unit") or "")
        unit = st.selectbox(
            "単位", UNIT_OPTIONS, index=UNIT_OPTIONS.index(unit_value) if unit_value in UNIT_OPTIONS else 0,
            key=f"capture-unit-{capture_id}",
        )
        consumed_quantity = st.number_input(
            "摂取した数量", min_value=0.0, max_value=float(quantity),
            value=min(float(item.get("consumed_quantity") or 0), float(quantity)), step=0.1,
            key=f"capture-consumed-{capture_id}",
        )
        nutrition = deepcopy(item.get("nutrition") or {})
        calories = _nutrition_input("1単位あたり Calories", nutrition.get("calories_kcal"), f"capture-kcal-{capture_id}")
        protein = _nutrition_input("1単位あたり Protein", nutrition.get("protein_g"), f"capture-p-{capture_id}")
        fat = _nutrition_input("1単位あたり Fat", nutrition.get("fat_g"), f"capture-f-{capture_id}")
        carbs = _nutrition_input("1単位あたり Carbs", nutrition.get("carbs_g"), f"capture-c-{capture_id}")
        basis = _nutrition_basis_input(nutrition, unit, f"capture-basis-{capture_id}")
        source_default = "商品ラベルで確認" if item.get("source_type") == "user_label" else "概算値として入力" if item.get("source_type") == "estimated" else "候補の値を使用"
        source_label = st.radio(
            "栄養値の由来", list(SOURCE_MODE_OPTIONS), index=list(SOURCE_MODE_OPTIONS).index(source_default),
            horizontal=True, key=f"capture-source-{capture_id}",
        )
        notes = st.text_input("備考", value=str(item.get("notes") or ""), key=f"capture-notes-{capture_id}")
        action_col1, action_col2 = st.columns(2)
        if action_col1.button("更新", key=f"capture-update-{capture_id}", width="stretch"):
            candidate = deepcopy(item)
            candidate["canonical_name"] = name
            candidate["display_name"] = name
            items[index] = prepare_capture_item(
                candidate,
                meal_type=meal_type,
                quantity=quantity,
                unit=unit,
                consumed_quantity=consumed_quantity,
                nutrition={
                    "basis": basis,
                    "calories_kcal": calories,
                    "protein_g": protein,
                    "fat_g": fat,
                    "carbs_g": carbs,
                    "sugar_g": None,
                    "fiber_g": None,
                    "salt_g": None,
                },
                source_mode=SOURCE_MODE_OPTIONS[source_label],
                notes=notes,
                capture_id=capture_id,
            )
            st.session_state[CAPTURE_STATE_KEY] = items
            st.rerun()
        if action_col2.button("削除", key=f"capture-delete-{capture_id}", width="stretch"):
            st.session_state[CAPTURE_STATE_KEY] = [value for position, value in enumerate(items) if position != index]
            st.rerun()


def render_smart_food_capture(
    repository: FoodMasterRepository,
    user_id: str,
    knowledge: dict[str, Any],
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

    query = st.text_input("食品を検索", placeholder="例：SAVAS BIO、理想のトマト、みたらし団子", key="smart-food-query")
    suggestions = search_food_candidates(query, knowledge)
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
        name = st.text_input("食品名", value=str(candidate.get("display_name") or query), key=f"new-name-{editor_key}")
        meal_type = st.selectbox(
            "食事区分", list(MEAL_LABELS), format_func=lambda value: MEAL_LABELS[value], key=f"new-meal-{editor_key}"
        )
        quantity = st.number_input("購入・用意した数量", min_value=0.1, value=float(candidate.get("quantity") or 1), step=0.1, key=f"new-quantity-{editor_key}")
        unit_value = str(candidate.get("unit") or "")
        unit = st.selectbox(
            "単位", UNIT_OPTIONS, index=UNIT_OPTIONS.index(unit_value) if unit_value in UNIT_OPTIONS else 0,
            key=f"new-unit-{editor_key}",
        )
        consumed_quantity = st.number_input(
            "摂取した数量", min_value=0.0, max_value=float(quantity), value=float(quantity), step=0.1,
            help="0なら購入・予定として保持され、Daily nutritionへ加算されません。",
            key=f"new-consumed-{editor_key}",
        )
        nutrition = deepcopy(candidate.get("nutrition") or {})
        calories = _nutrition_input("1単位あたり Calories", nutrition.get("calories_kcal"), f"new-kcal-{editor_key}")
        protein = _nutrition_input("1単位あたり Protein", nutrition.get("protein_g"), f"new-p-{editor_key}")
        fat = _nutrition_input("1単位あたり Fat", nutrition.get("fat_g"), f"new-f-{editor_key}")
        carbs = _nutrition_input("1単位あたり Carbs", nutrition.get("carbs_g"), f"new-c-{editor_key}")
        basis = _nutrition_basis_input(nutrition, unit, f"new-basis-{editor_key}")
        source_default = "概算値として入力" if candidate.get("source_type") in {"unknown", "estimated"} and calories is not None else "候補の値を使用"
        source_label = st.radio(
            "栄養値の由来", list(SOURCE_MODE_OPTIONS), index=list(SOURCE_MODE_OPTIONS).index(source_default),
            horizontal=True, key=f"new-source-{editor_key}",
        )
        notes = st.text_input("備考", key=f"new-notes-{editor_key}")
        remember = st.checkbox("この食品の栄養値を今後も使用する", key=f"new-remember-{editor_key}")
        if st.button("食品を追加", type="primary", key=f"new-add-{editor_key}"):
            candidate["canonical_name"] = name
            candidate["display_name"] = name
            prepared = prepare_capture_item(
                candidate,
                meal_type=meal_type,
                quantity=quantity,
                unit=unit,
                consumed_quantity=consumed_quantity,
                nutrition={
                    "basis": basis,
                    "calories_kcal": calories,
                    "protein_g": protein,
                    "fat_g": fat,
                    "carbs_g": carbs,
                    "sugar_g": None,
                    "fiber_g": None,
                    "salt_g": None,
                },
                source_mode=SOURCE_MODE_OPTIONS[source_label],
                notes=notes,
            )
            if remember:
                if prepared["source_type"] != "user_label":
                    st.error("今後も使う値は「商品ラベルで確認」を選択してください。概算値は確定保存しません。")
                    return deepcopy(items)
                stored = confirm_capture_food(repository, user_id, prepared)
                prepared["food_id"] = stored.get("food_id")
                prepared["source_detail"] = "過去の確認値"
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


__all__ = ["CAPTURE_STATE_KEY", "render_smart_food_capture"]
