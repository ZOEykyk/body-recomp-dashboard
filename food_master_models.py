from __future__ import annotations

from copy import deepcopy
import datetime as dt
from typing import Any
from uuid import uuid4


FOOD_MASTER_VERSION = "1.0"
FOOD_STATUSES = {"candidate", "active", "archived"}
REVIEW_STATUSES = {"pending_review", "reviewed", "rejected"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def new_food_id() -> str:
    return f"pfm_{uuid4().hex}"


def new_encounter_id() -> str:
    return f"enc_{uuid4().hex}"


def parsed_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "brand": item.get("brand"),
        "canonical_name": item.get("canonical_name"),
        "variant": item.get("variant"),
        "size": item.get("size"),
        "quantity": item.get("quantity"),
        "unit": item.get("unit"),
        "original_fragment": item.get("original_fragment") or item.get("raw_text"),
    }


def new_food_record(
    user_id: str,
    item: dict[str, Any],
    *,
    status: str = "candidate",
    review_status: str = "pending_review",
    nutrition_sources: list[dict[str, Any]] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or utc_now()
    identity = parsed_identity(item)
    alias = identity["original_fragment"]
    aliases = [alias] if alias else []
    return {
        "food_id": new_food_id(),
        "user_id": user_id,
        "brand": identity["brand"],
        "canonical_name": identity["canonical_name"],
        "variant": identity["variant"],
        "size": identity["size"],
        "aliases": aliases,
        "status": status,
        "review_status": review_status,
        "nutrition_sources": deepcopy(nutrition_sources or []),
        "usage_count": 0,
        "first_used_at": None,
        "last_used_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def touch_food_usage(food: dict[str, Any], used_at: str | None = None) -> dict[str, Any]:
    updated = deepcopy(food)
    timestamp = used_at or utc_now()
    updated["usage_count"] = int(updated.get("usage_count") or 0) + 1
    updated["first_used_at"] = updated.get("first_used_at") or timestamp
    updated["last_used_at"] = timestamp
    updated["updated_at"] = timestamp
    return updated
