from __future__ import annotations

from copy import deepcopy

import streamlit as st

from food_master_repository import FoodMasterRepository
from personal_food_master import link_candidate_to_food, personal_food_source_selection, promote_food


def _source_type(food: dict) -> str:
    selection = personal_food_source_selection(food)
    selected = selection.get("selected") or {}
    return str((selected.get("source") or {}).get("source_type") or "—")


def _food_title(food: dict) -> str:
    brand = str(food.get("brand") or "").strip()
    name = str(food.get("canonical_name") or "未確認食品").strip()
    return f"{brand} {name}".strip()


def _add_alias(repository: FoodMasterRepository, user_id: str, food: dict, alias: str) -> None:
    value = alias.strip()
    if not value:
        return
    updated = deepcopy(food)
    updated["aliases"] = sorted(set(updated.get("aliases") or []) | {value})
    updated["updated_by"] = "user"
    repository.upsert_food(user_id, updated)


def _food_summary(food: dict) -> None:
    st.markdown(f"**{_food_title(food)}**")
    st.caption(
        f"使用 {food.get('use_count', food.get('usage_count', 0))}回 / "
        f"最終使用 {food.get('last_used_at') or '—'} / "
        f"source {_source_type(food)} / review {food.get('review_status') or '—'}"
    )
    aliases = food.get("aliases") or []
    if aliases:
        st.caption(f"Alias: {', '.join(str(alias) for alias in aliases)}")


def render_food_master_management(repository: FoodMasterRepository, user_id: str) -> None:
    """Compact management UI that never reads or writes records.csv."""
    foods = repository.list_foods(user_id)
    active_foods = [food for food in foods if food.get("status") == "active"]
    candidates = repository.list_candidates(user_id)

    st.header("Personal Food Master")
    with st.expander(f"食品管理: active {len(active_foods)}件 / candidate {len(candidates)}件", expanded=False):
        if not foods:
            st.caption("新しい記録を保存すると、食品遭遇がここに蓄積されます。")
            return

        st.subheader("Active Foods")
        if not active_foods:
            st.caption("active foodはまだありません。")
        for food in active_foods:
            _food_summary(food)
            alias = st.text_input("Aliasを追加", key=f"food-master-alias-{food['food_id']}")
            if st.button("Aliasを保存", key=f"food-master-alias-save-{food['food_id']}"):
                _add_alias(repository, user_id, food, alias)
                st.rerun()
            if st.button("Archive", key=f"food-master-archive-{food['food_id']}"):
                repository.archive_food(user_id, food["food_id"])
                st.rerun()
            st.divider()

        st.subheader("Pending Candidates")
        if not candidates:
            st.caption("pending candidateはありません。")
        existing_options = {food["food_id"]: _food_title(food) for food in active_foods}
        for candidate in candidates:
            _food_summary(candidate)
            if st.button("候補を確認して有効化", key=f"food-master-confirm-{candidate['food_id']}"):
                try:
                    repository.upsert_food(user_id, promote_food(candidate, reviewer="user"))
                    st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))
            if existing_options:
                existing_id = st.selectbox(
                    "既存foodへリンク",
                    options=[""] + list(existing_options),
                    format_func=lambda value: existing_options.get(value, "選択してください"),
                    key=f"food-master-link-select-{candidate['food_id']}",
                )
                if st.button("選択したfoodへリンク", key=f"food-master-link-{candidate['food_id']}") and existing_id:
                    existing = repository.get_food(user_id, existing_id)
                    if existing:
                        repository.upsert_food(user_id, link_candidate_to_food(existing, candidate))
                        repository.archive_food(user_id, candidate["food_id"])
                        st.rerun()
            alias = st.text_input("Aliasを追加", key=f"food-master-candidate-alias-{candidate['food_id']}")
            if st.button("Aliasを保存", key=f"food-master-candidate-alias-save-{candidate['food_id']}"):
                _add_alias(repository, user_id, candidate, alias)
                st.rerun()
            if st.button("Archive", key=f"food-master-candidate-archive-{candidate['food_id']}"):
                repository.archive_food(user_id, candidate["food_id"])
                st.rerun()
            st.divider()
