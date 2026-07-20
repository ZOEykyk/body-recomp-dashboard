from __future__ import annotations

from copy import deepcopy
import datetime as dt
import html
from typing import Any

import streamlit as st

from food_lookup import FOOD_LOOKUP_CATALOG
from food_master_repository import FoodMasterRepository


CONFIDENCE_SCORES = {"high": 1.0, "medium": 0.65, "low": 0.3}


def _food_title(food: dict[str, Any]) -> str:
    return " ".join(
        str(value).strip()
        for value in (food.get("brand"), food.get("canonical_name"), food.get("variant"), food.get("size"))
        if value and str(value).strip()
    ) or "未確認食品"


def _encounter_confidence(encounter: dict[str, Any]) -> str:
    explicit = str(encounter.get("resolution_confidence") or "")
    if explicit in CONFIDENCE_SCORES:
        return explicit
    source_type = str(encounter.get("selected_source_type") or "")
    if source_type == "fallback_estimate":
        return "low"
    if source_type == "legacy_dictionary":
        return "medium"
    return "high" if source_type else "low"


def _display_timestamp(value: Any) -> str:
    if not value:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def food_knowledge_metrics(repository: FoodMasterRepository, user_id: str) -> dict[str, Any]:
    """Build a UI-neutral Food Knowledge projection from repository contracts."""
    snapshot = repository.get_knowledge_snapshot(user_id, include_encounters=True)
    foods = [food for food in snapshot["personal_foods"] if food.get("status") != "archived"]
    active = [food for food in foods if food.get("status") == "active"]
    encounters = snapshot["encounters"]
    fallback_count = sum(
        encounter.get("resolution_origin") == "fallback"
        or encounter.get("selected_source_type") == "fallback_estimate"
        or (
            not encounter.get("selected_source_type")
            and encounter.get("resolution_status") in {"not_found", "candidate_reused"}
        )
        for encounter in encounters
    )
    confidence_values = [CONFIDENCE_SCORES[_encounter_confidence(encounter)] for encounter in encounters]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
    usage_ranking = repository.list_top_used_foods(user_id, limit=5)
    recently_added = sorted(foods, key=lambda food: str(food.get("created_at") or ""), reverse=True)[:3]
    recently_updated = repository.list_recent_foods(user_id, limit=3)
    return {
        "registered_count": len(foods) + len(FOOD_LOOKUP_CATALOG),
        "personal_count": len(active),
        "candidate_count": len(foods) - len(active),
        "official_count": len(FOOD_LOOKUP_CATALOG),
        "fallback_count": int(fallback_count),
        "confidence": confidence,
        "usage_ranking": deepcopy(usage_ranking),
        "recently_added": deepcopy(recently_added),
        "recently_updated": deepcopy(recently_updated),
        "repository_status": repository.get_repository_status(),
    }


def _list_markup(items: list[dict[str, Any]], *, usage: bool = False) -> str:
    if not items:
        return '<div class="bodyos-fk-empty">まだデータがありません</div>'
    rows = []
    for index, food in enumerate(items, start=1):
        suffix = ""
        if usage:
            count = int(food.get("use_count", food.get("usage_count", 0)) or 0)
            suffix = f'<span class="bodyos-fk-count">{count}回</span>'
        rows.append(
            '<div class="bodyos-fk-row">'
            f'<span class="bodyos-fk-rank">{index}</span>'
            f'<span class="bodyos-fk-name">{html.escape(_food_title(food))}</span>{suffix}'
            "</div>"
        )
    return "".join(rows)


def render_food_knowledge_dashboard(repository: FoodMasterRepository, user_id: str) -> None:
    try:
        metrics = food_knowledge_metrics(repository, user_id)
    except Exception:
        metrics = {
            "registered_count": len(FOOD_LOOKUP_CATALOG),
            "personal_count": 0,
            "candidate_count": 0,
            "official_count": len(FOOD_LOOKUP_CATALOG),
            "fallback_count": 0,
            "confidence": None,
            "usage_ranking": [],
            "recently_added": [],
            "recently_updated": [],
            "repository_status": repository.get_repository_status(),
        }
    confidence = "—" if metrics["confidence"] is None else f"{metrics['confidence']:.0%}"
    cards = [
        ("登録食品", str(metrics["registered_count"]), "Official + Personal"),
        ("Personal Food", str(metrics["personal_count"]), f"確認待ち {metrics['candidate_count']}"),
        ("Official Food", str(metrics["official_count"]), "reviewed catalog"),
        ("Fallback", str(metrics["fallback_count"]), "記録済みEncounter"),
        ("Confidence", confidence, "Encounter平均"),
    ]
    card_markup = "".join(
        '<div class="bodyos-fk-card">'
        f'<div class="bodyos-fk-label">{html.escape(label)}</div>'
        f'<div class="bodyos-fk-value">{html.escape(value)}</div>'
        f'<div class="bodyos-fk-meta">{html.escape(meta)}</div>'
        "</div>"
        for label, value, meta in cards
    )
    storage = metrics["repository_status"]
    storage_cards = [
        ("Storage", str(storage.get("storage") or "—"), "Active backend"),
        ("Connection", str(storage.get("connection") or "—"), "Repository health"),
        ("Repository", str(storage.get("repository") or "—"), "Adapter"),
        ("Last Write", _display_timestamp(storage.get("last_successful_write")), "Food Knowledge"),
        ("Last Read", _display_timestamp(storage.get("last_successful_read")), "Food Knowledge"),
        ("Migration", str(storage.get("migration_status") or "—"), "Schema"),
        ("未同期", str(storage.get("unsynced_count") or 0), "Fallback queue"),
    ]
    storage_markup = "".join(
        '<div class="bodyos-fk-card bodyos-fk-storage-card">'
        f'<div class="bodyos-fk-label">{html.escape(label)}</div>'
        f'<div class="bodyos-fk-storage-value">{html.escape(value)}</div>'
        f'<div class="bodyos-fk-meta">{html.escape(meta)}</div>'
        "</div>"
        for label, value, meta in storage_cards
    )
    st.header("Food Knowledge")
    st.caption("食品知識の蓄積状況。すべての解決経路は共通Food ResolverとSource Policyを利用します。")
    st.markdown(
        f"""
        <style>
          .bodyos-food-knowledge, .bodyos-food-knowledge * {{ box-sizing: border-box; min-width: 0; }}
          .bodyos-food-knowledge {{ color: #31313f; width: 100%; }}
          .bodyos-food-knowledge .bodyos-fk-grid {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0.75rem; }}
          .bodyos-food-knowledge .bodyos-fk-storage-grid {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
          .bodyos-food-knowledge .bodyos-fk-card {{ border: 1px solid rgba(49,51,63,.16); border-radius: 8px; padding: .8rem .9rem; background: #fff; }}
          .bodyos-food-knowledge .bodyos-fk-label {{ color: #31313f; font-size: .9rem; font-weight: 700; line-height: 1.35; }}
          .bodyos-food-knowledge .bodyos-fk-value {{ color: #31313f; font-size: 1.8rem; font-weight: 750; line-height: 1.15; margin: .35rem 0 .25rem; }}
          .bodyos-food-knowledge .bodyos-fk-storage-value {{ color: #31313f; font-size: 1rem; font-weight: 750; line-height: 1.35; margin: .35rem 0 .25rem; overflow-wrap: anywhere; }}
          .bodyos-food-knowledge .bodyos-fk-meta, .bodyos-food-knowledge .bodyos-fk-empty {{ color: rgba(49,51,63,.68); font-size: .82rem; line-height: 1.4; }}
          .bodyos-food-knowledge .bodyos-fk-detail-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .75rem; margin-top: .8rem; }}
          .bodyos-food-knowledge .bodyos-fk-panel {{ border-top: 1px solid rgba(49,51,63,.16); padding-top: .65rem; }}
          .bodyos-food-knowledge .bodyos-fk-heading {{ color: #31313f; font-weight: 750; margin-bottom: .4rem; }}
          .bodyos-food-knowledge .bodyos-fk-row {{ display: grid; grid-template-columns: 1.2rem minmax(0, 1fr) auto; gap: .35rem; align-items: start; padding: .28rem 0; }}
          .bodyos-food-knowledge .bodyos-fk-rank, .bodyos-food-knowledge .bodyos-fk-count {{ color: rgba(49,51,63,.62); font-size: .78rem; }}
          .bodyos-food-knowledge .bodyos-fk-name {{ color: #31313f; font-size: .88rem; line-height: 1.4; overflow-wrap: anywhere; }}
          @media (max-width: 900px) {{
            .bodyos-food-knowledge .bodyos-fk-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
            .bodyos-food-knowledge .bodyos-fk-detail-grid {{ grid-template-columns: minmax(0, 1fr); }}
          }}
          @media (max-width: 520px) {{
            .bodyos-food-knowledge .bodyos-fk-grid {{ grid-template-columns: minmax(0, 1fr); }}
            .bodyos-food-knowledge .bodyos-fk-value {{ font-size: 1.65rem; }}
          }}
        </style>
        <section class="bodyos-food-knowledge">
          <div class="bodyos-fk-heading">保存基盤</div>
          <div class="bodyos-fk-grid bodyos-fk-storage-grid">{storage_markup}</div>
          <div class="bodyos-fk-heading" style="margin-top: 1rem;">Knowledge Metrics</div>
          <div class="bodyos-fk-grid">{card_markup}</div>
          <div class="bodyos-fk-detail-grid">
            <div class="bodyos-fk-panel"><div class="bodyos-fk-heading">利用回数ランキング</div>{_list_markup(metrics['usage_ranking'], usage=True)}</div>
            <div class="bodyos-fk-panel"><div class="bodyos-fk-heading">最近追加</div>{_list_markup(metrics['recently_added'])}</div>
            <div class="bodyos-fk-panel"><div class="bodyos-fk-heading">最近更新</div>{_list_markup(metrics['recently_updated'])}</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if storage.get("warning"):
        st.warning(str(storage["warning"]))


__all__ = ["food_knowledge_metrics", "render_food_knowledge_dashboard"]
