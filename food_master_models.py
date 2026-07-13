from __future__ import annotations

from copy import deepcopy
import datetime as dt
import hashlib
import json
from typing import Any
from uuid import uuid4


FOOD_MASTER_VERSION = "1.0"
FOOD_MASTER_SCHEMA_VERSION = "1.1"
FOOD_ENCOUNTER_SCHEMA_VERSION = "1.1"
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


def normalized_identity_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    identity = parsed_identity(item)
    return tuple(" ".join(str(identity[field] or "").lower().split()) for field in ("brand", "canonical_name", "variant", "size"))


def encounter_idempotency_key(
    owner_user_id: str,
    record_date: str,
    meal_type: str,
    original_fragment: str,
    operation_id: str,
) -> str:
    payload = {
        "owner_user_id": owner_user_id,
        "record_date": record_date,
        "meal_type": meal_type,
        "normalized_fragment": " ".join(str(original_fragment or "").lower().split()),
        "operation_id": operation_id,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"enc_v1_{hashlib.sha256(encoded).hexdigest()}"


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
        "owner_user_id": user_id,
        "scope": "personal",
        "brand": identity["brand"],
        "canonical_name": identity["canonical_name"],
        "variant": identity["variant"],
        "size": identity["size"],
        "aliases": aliases,
        "category": None,
        "default_quantity": identity["quantity"],
        "default_unit": identity["unit"],
        "notes": None,
        "status": status,
        "review_status": review_status,
        "nutrition_sources": deepcopy(nutrition_sources or []),
        "use_count": 0,
        "usage_count": 0,
        "first_used_at": None,
        "last_used_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "schema_version": FOOD_MASTER_SCHEMA_VERSION,
        "created_by": "system",
        "updated_by": "system",
    }


def touch_food_usage(food: dict[str, Any], used_at: str | None = None) -> dict[str, Any]:
    updated = deepcopy(food)
    timestamp = used_at or utc_now()
    next_count = max(int(updated.get("usage_count") or 0), int(updated.get("use_count") or 0)) + 1
    updated["usage_count"] = next_count
    updated["use_count"] = next_count
    updated["first_used_at"] = updated.get("first_used_at") or timestamp
    updated["last_used_at"] = timestamp
    updated["updated_at"] = timestamp
    return updated
