from __future__ import annotations

from copy import deepcopy
from typing import Any

from food_aliases import normalize_food_name
from food_lookup import lookup_food
from food_master_models import new_encounter_id, new_food_record, parsed_identity, touch_food_usage, utc_now
from food_master_repository import FoodMasterRepository
from food_source_models import explicit_user_label_source
from food_source_policy import select_nutrition_source


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


def remember_food_encounters(
    repository: FoodMasterRepository,
    user_id: str,
    parsed_foods: dict[str, Any],
    *,
    meal_type: str,
    used_at: str | None = None,
) -> list[dict[str, Any]]:
    """Append encounters and create reviewable knowledge only for a newly saved record."""
    if not isinstance(parsed_foods, dict) or parsed_foods.get("is_zero_meal"):
        return []
    timestamp = used_at or utc_now()
    foods = repository.list_foods(user_id)
    encounters: list[dict[str, Any]] = []
    for item in parsed_foods.get("items") or []:
        if not isinstance(item, dict) or not item.get("original_fragment"):
            continue
        personal_resolution = resolve_personal_food(item, foods)
        master_food = personal_resolution.get("food")
        seed_lookup = lookup_food(item)
        if master_food is not None:
            source_selection = personal_food_source_selection(master_food)
        elif seed_lookup.get("status") == "matched":
            source_selection = seed_lookup["source_selection"]
        elif item.get("explicit_nutrition", {}).get("calories_kcal") is not None:
            source_selection = select_nutrition_source(
                [{"source": explicit_user_label_source(notes="Explicit nutrition extracted from meal text."), "nutrition": item["explicit_nutrition"]}]
            )
        else:
            source_selection = select_nutrition_source([])

        if master_food is None:
            master_food = create_food_from_encounter(user_id, item, source_selection, now=timestamp)
        aliases = set(master_food.get("aliases") or [])
        aliases.add(str(item["original_fragment"]))
        master_food["aliases"] = sorted(alias for alias in aliases if alias)
        master_food = touch_food_usage(master_food, timestamp)
        master_food = repository.upsert_food(user_id, master_food)
        foods = [food for food in foods if food.get("food_id") != master_food["food_id"]] + [master_food]

        encounter = {
            "encounter_id": new_encounter_id(),
            "occurred_at": timestamp,
            "meal_type": meal_type,
            "parsed_identity": parsed_identity(item),
            "personal_resolution": personal_resolution["status"],
            "seed_lookup_status": seed_lookup.get("status"),
            "source_selection": source_selection,
            "food_id": master_food["food_id"],
        }
        encounters.append(repository.append_encounter(user_id, encounter))
    return encounters
