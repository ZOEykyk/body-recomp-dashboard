from __future__ import annotations

from copy import deepcopy
from typing import Any

from food_aliases import normalize_food_name
from food_lookup import FOOD_LOOKUP_VERSION
from food_master_models import (
    FOOD_ENCOUNTER_SCHEMA_VERSION,
    encounter_idempotency_key,
    new_encounter_id,
    new_food_record,
    normalized_identity_key,
    parsed_identity,
    touch_food_usage,
    utc_now,
)
from food_master_repository import FoodMasterRepository
from food_source_policy import FOOD_SOURCE_POLICY_VERSION, select_nutrition_source


AUTHORITATIVE_TYPES = {"official_product_page", "official_nutrition_table", "official_api_or_catalog", "bodyos_verified"}


def _key(value: Any) -> str:
    return normalize_food_name(value).lower().replace(" ", "")


def _matches_identity(item: dict[str, Any], food: dict[str, Any]) -> bool:
    item_name = _key(item.get("canonical_name") or item.get("original_fragment") or item.get("raw_text"))
    aliases = [food.get("canonical_name"), *(food.get("aliases") or [])]
    if not item_name or item_name not in {_key(alias) for alias in aliases if _key(alias)}:
        return False
    item_brand = _key(item.get("brand"))
    food_brand = _key(food.get("brand"))
    return not item_brand or not food_brand or item_brand == food_brand


def resolve_personal_food(item: dict[str, Any], foods: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [food for food in foods if food.get("status") == "active" and _matches_identity(item, food)]
    if len(candidates) == 1:
        return {"status": "matched", "food": deepcopy(candidates[0]), "candidates": [], "needs_review": False}
    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "food": None,
            "candidates": [deepcopy(food) for food in candidates],
            "needs_review": True,
        }
    return {"status": "not_found", "food": None, "candidates": [], "needs_review": False}


def find_existing_candidate(item: dict[str, Any], foods: list[dict[str, Any]]) -> dict[str, Any] | None:
    identity = normalized_identity_key(item)
    matches = [food for food in foods if food.get("status") == "candidate" and normalized_identity_key(food) == identity]
    return deepcopy(matches[0]) if len(matches) == 1 else None


def personal_food_source_selection(food: dict[str, Any]) -> dict[str, Any]:
    return select_nutrition_source(deepcopy(food.get("nutrition_sources") or []))


def can_activate_from_source_selection(source_selection: dict[str, Any]) -> bool:
    selected = source_selection.get("selected") if isinstance(source_selection, dict) else None
    source = selected.get("source") if isinstance(selected, dict) else None
    return bool(
        selected
        and not source_selection.get("needs_review")
        and source.get("source_type") in AUTHORITATIVE_TYPES
        and source.get("verification_status") == "verified"
    )


def create_food_from_encounter(
    user_id: str,
    item: dict[str, Any],
    source_selection: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    selected = source_selection.get("selected") if isinstance(source_selection, dict) else None
    nutrition_sources = [{"source": selected["source"], "nutrition": selected["nutrition"]}] if selected else []
    status = "active" if can_activate_from_source_selection(source_selection) else "candidate"
    review_status = "reviewed" if status == "active" else "pending_review"
    return new_food_record(
        user_id,
        item,
        status=status,
        review_status=review_status,
        nutrition_sources=nutrition_sources,
        now=now,
    )


def promote_food(food: dict[str, Any], *, reviewer: str = "user", now: str | None = None) -> dict[str, Any]:
    promoted = deepcopy(food)
    selection = personal_food_source_selection(promoted)
    if not selection.get("selected"):
        raise ValueError("A nutrition source is required before promotion.")
    promoted["status"] = "active"
    promoted["review_status"] = "reviewed"
    promoted["updated_at"] = now or utc_now()
    for candidate in promoted.get("nutrition_sources", []):
        source = candidate.get("source")
        if isinstance(source, dict) and source.get("source_type") == "explicit_user_label":
            source["reviewer"] = reviewer
            source["verification_status"] = "verified"
    return promoted


def link_candidate_to_food(existing_food: dict[str, Any], candidate_food: dict[str, Any], *, updated_by: str = "user") -> dict[str, Any]:
    linked = deepcopy(existing_food)
    aliases = set(linked.get("aliases") or []) | set(candidate_food.get("aliases") or [])
    linked["aliases"] = sorted(alias for alias in aliases if alias)
    known_source_ids = {
        source.get("source", {}).get("source_id")
        for source in linked.get("nutrition_sources") or []
        if isinstance(source, dict)
    }
    for source in candidate_food.get("nutrition_sources") or []:
        source_id = source.get("source", {}).get("source_id") if isinstance(source, dict) else None
        if source_id not in known_source_ids:
            linked.setdefault("nutrition_sources", []).append(deepcopy(source))
            known_source_ids.add(source_id)
    linked["updated_by"] = updated_by
    linked["updated_at"] = utc_now()
    return linked


def remember_food_encounters(
    repository: FoodMasterRepository,
    user_id: str,
    parsed_foods: dict[str, Any],
    *,
    meal_type: str,
    record_date: str,
    operation_id: str,
    used_at: str | None = None,
    resolution: dict[str, Any] | None = None,
    knowledge: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Append encounters and create reviewable knowledge only for a newly saved record."""
    result = _remember_food_encounters(
        repository,
        user_id,
        parsed_foods,
        meal_type=meal_type,
        record_date=record_date,
        operation_id=operation_id,
        used_at=used_at,
        resolution=resolution,
        knowledge=knowledge,
        raise_on_error=True,
    )
    return result["encounters"]


def remember_food_encounters_with_summary(
    repository: FoodMasterRepository,
    user_id: str,
    parsed_foods: dict[str, Any],
    *,
    meal_type: str,
    record_date: str,
    operation_id: str,
    used_at: str | None = None,
    resolution: dict[str, Any] | None = None,
    knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist encounters and expose operational counts without changing domain records."""
    return _remember_food_encounters(
        repository,
        user_id,
        parsed_foods,
        meal_type=meal_type,
        record_date=record_date,
        operation_id=operation_id,
        used_at=used_at,
        resolution=resolution,
        knowledge=knowledge,
        raise_on_error=False,
    )


def _remember_food_encounters(
    repository: FoodMasterRepository,
    user_id: str,
    parsed_foods: dict[str, Any],
    *,
    meal_type: str,
    record_date: str,
    operation_id: str,
    used_at: str | None,
    resolution: dict[str, Any] | None,
    knowledge: dict[str, Any] | None,
    raise_on_error: bool,
) -> dict[str, Any]:
    if not isinstance(parsed_foods, dict) or parsed_foods.get("is_zero_meal"):
        return {"encounters": [], "saved": 0, "duplicates": 0, "failed": 0, "errors": []}
    timestamp = used_at or utc_now()
    if not isinstance(resolution, dict):
        from food_resolver import build_food_knowledge_snapshot, resolve_food_text

        if knowledge is None:
            repository_snapshot = repository.build_snapshot(user_id)
            knowledge = build_food_knowledge_snapshot(repository_snapshot["personal_foods"])
        resolver_knowledge = knowledge
        resolution = resolve_food_text(
            str(parsed_foods.get("raw_text") or ""),
            meal_type,
            knowledge=resolver_knowledge,
        )
    resolved_items = {
        int(result.get("item", {}).get("index", -1)): result
        for result in resolution.get("items") or []
        if isinstance(result, dict)
    }
    encounters: list[dict[str, Any]] = []
    duplicates = 0
    failed = 0
    errors: list[str] = []
    for item in parsed_foods.get("items") or []:
        if not isinstance(item, dict) or not item.get("original_fragment"):
            continue
        idempotency_key = encounter_idempotency_key(
            user_id,
            record_date,
            meal_type,
            str(item["original_fragment"]),
            operation_id,
        )
        item_resolution = resolved_items.get(int(item.get("index", -1)), {})
        selected = item_resolution.get("selected") or {}
        source_selection = item_resolution.get("source_selection") or select_nutrition_source([])
        selected_origin = str(item_resolution.get("selected_origin") or "fallback")
        selected_food = selected.get("food") if isinstance(selected.get("food"), dict) else None
        master_food = deepcopy(selected_food) if selected_origin == "personal" and selected_food else None
        personal_resolution = {
            "status": "matched" if master_food is not None else str(item_resolution.get("status") or "not_found"),
            "food": master_food,
        }

        candidate_reason: str | None = None
        if master_food is None:
            candidates = [
                candidate
                for candidate in repository.find_food_candidates(user_id, item)
                if candidate.get("status") == "candidate"
            ]
            master_food = deepcopy(candidates[0]) if len(candidates) == 1 else None
            if master_food is not None:
                candidate_reason = "existing_candidate"
                personal_resolution = {"status": "candidate_reused", "food": master_food}
        if master_food is None:
            knowledge_selection = (
                source_selection
                if selected_origin in {"explicit", "official"}
                else select_nutrition_source([])
            )
            master_food = create_food_from_encounter(user_id, item, knowledge_selection, now=timestamp)
            candidate_reason = "new_candidate" if master_food["status"] == "candidate" else "authoritative_source"
        aliases = set(master_food.get("aliases") or [])
        aliases.add(str(item["original_fragment"]))
        master_food["aliases"] = sorted(alias for alias in aliases if alias)
        master_food = touch_food_usage(master_food, timestamp)

        encounter = {
            "encounter_id": new_encounter_id(),
            "idempotency_key": idempotency_key,
            "owner_user_id": user_id,
            "record_date": record_date,
            "occurred_at": timestamp,
            "meal_type": meal_type,
            "original_text": parsed_foods.get("raw_text"),
            "original_fragment": item["original_fragment"],
            "parsed_identity": parsed_identity(item),
            "resolved_food_id": master_food["food_id"],
            "resolution_status": personal_resolution["status"],
            "selected_source_type": (source_selection.get("selected") or {}).get("source", {}).get("source_type"),
            "selected_source_id": (source_selection.get("selected") or {}).get("source", {}).get("source_id"),
            "selected_nutrition": item_resolution.get("total_nutrition") or (source_selection.get("selected") or {}).get("nutrition"),
            "resolution_origin": selected_origin,
            "resolution_confidence": item_resolution.get("confidence") or "low",
            "quantity": item.get("quantity"),
            "unit": item.get("unit"),
            "parser_version": parsed_foods.get("metadata", {}).get("food_parser_version"),
            "lookup_version": FOOD_LOOKUP_VERSION,
            "source_policy_version": FOOD_SOURCE_POLICY_VERSION,
            "resolver_version": resolution.get("metadata", {}).get("food_resolver_version"),
            "needs_review": bool(source_selection.get("needs_review") or master_food.get("status") == "candidate"),
            "candidate_reason": candidate_reason,
            "created_at": timestamp,
            "schema_version": FOOD_ENCOUNTER_SCHEMA_VERSION,
        }
        try:
            persistence = repository.save_encounter_idempotently(user_id, master_food, encounter)
        except Exception as exc:
            if raise_on_error:
                raise
            failed += 1
            errors.append(f"{item.get('original_fragment')}: {type(exc).__name__}")
            continue
        if persistence.get("duplicate"):
            duplicates += 1
            continue
        stored_food = persistence.get("food") if isinstance(persistence.get("food"), dict) else master_food
        stored_encounter = (
            persistence.get("encounter") if isinstance(persistence.get("encounter"), dict) else encounter
        )
        encounters.append(stored_encounter)
    return {
        "encounters": encounters,
        "saved": len(encounters),
        "duplicates": duplicates,
        "failed": failed,
        "errors": errors,
    }
