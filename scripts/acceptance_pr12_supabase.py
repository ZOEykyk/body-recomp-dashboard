from __future__ import annotations

import argparse
from copy import deepcopy
import datetime as dt
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib import parse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from food_master_models import FOOD_ENCOUNTER_SCHEMA_VERSION, new_food_record, touch_food_usage
from supabase_food_master_repository import SupabaseFoodMasterRepository, SupabaseRestClient


DEFAULT_STATE_PATH = ROOT / "validation_artifacts" / "pr12-acceptance-state.json"
ACCEPTANCE_OWNER_PREFIX = "pr12-acceptance-"


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _repository() -> SupabaseFoodMasterRepository:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (
        os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and a Supabase secret/service-role key are required")
    timeout = float(os.environ.get("SUPABASE_TIMEOUT_SECONDS", "8"))
    repository = SupabaseFoodMasterRepository(SupabaseRestClient(url, key, timeout=timeout))
    repository.health_check()
    return repository


def _fixture(run_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    owner = f"{ACCEPTANCE_OWNER_PREFIX}{run_id}"
    timestamp = _utc_now()
    item = {
        "brand": "BodyOS",
        "canonical_name": f"PR12 Acceptance Food {run_id}",
        "variant": None,
        "size": "1個",
        "quantity": 1,
        "unit": "piece",
        "original_fragment": f"PR12 Acceptance Food {run_id}",
    }
    source = {
        "source_id": "explicit-user-label",
        "source_type": "explicit_user_label",
        "publisher": "PR12 Acceptance Test",
        "source_ref": None,
        "captured_at": timestamp,
        "verified_at": None,
        "valid_from": None,
        "valid_to": None,
        "product_version": None,
        "reviewer": None,
        "verification_status": "pending_review",
        "confidence": "high",
        "notes": "Disposable PR12 acceptance fixture.",
    }
    nutrition = {
        "basis": "per_item",
        "serving_quantity": 1,
        "serving_unit": "piece",
        "calories_kcal": 123,
        "protein_g": 10,
        "fat_g": 4,
        "carbs_g": 12,
        "sugar_g": None,
        "fiber_g": None,
        "salt_g": 0.5,
    }
    food = new_food_record(
        owner,
        item,
        status="active",
        review_status="reviewed",
        nutrition_sources=[{"source": source, "nutrition": nutrition}],
        now=timestamp,
    )
    food["food_id"] = f"pr12_food_{run_id}"
    food = touch_food_usage(food, timestamp)
    encounter = {
        "encounter_id": f"pr12_encounter_{run_id}",
        "idempotency_key": f"pr12_idempotency_{run_id}",
        "owner_user_id": owner,
        "record_date": timestamp[:10],
        "occurred_at": timestamp,
        "meal_type": "acceptance",
        "original_text": item["original_fragment"],
        "original_fragment": item["original_fragment"],
        "parsed_identity": deepcopy(item),
        "resolved_food_id": food["food_id"],
        "resolution_status": "matched",
        "selected_source_type": source["source_type"],
        "selected_source_id": source["source_id"],
        "selected_nutrition": deepcopy(nutrition),
        "resolution_origin": "explicit",
        "resolution_confidence": "high",
        "quantity": 1,
        "unit": "piece",
        "parser_version": "acceptance",
        "lookup_version": "acceptance",
        "source_policy_version": "acceptance",
        "resolver_version": "acceptance",
        "needs_review": False,
        "candidate_reason": "acceptance_fixture",
        "created_at": timestamp,
        "schema_version": FOOD_ENCOUNTER_SCHEMA_VERSION,
    }
    return owner, food, encounter


def _assert_fixture(repository: SupabaseFoodMasterRepository, state: dict[str, Any]) -> dict[str, Any]:
    owner = str(state["owner_user_id"])
    food = repository.get_food(owner, str(state["food_id"]))
    encounter = repository.get_encounter_by_idempotency(owner, str(state["idempotency_key"]))
    if food is None:
        raise AssertionError("Personal Food did not persist")
    if encounter is None:
        raise AssertionError("Food Encounter did not persist")
    if int(food.get("usage_count") or 0) != int(state["expected_usage_count"]):
        raise AssertionError("usage_count changed unexpectedly")
    nutrition_sources = food.get("nutrition_sources") or []
    if not nutrition_sources or nutrition_sources[0].get("nutrition", {}).get("calories_kcal") != 123:
        raise AssertionError("Nutrition source/fact did not round-trip")
    return {
        "food_present": True,
        "encounter_present": True,
        "usage_count": int(food.get("usage_count") or 0),
        "alias_count": len(food.get("aliases") or []),
        "nutrition_source_count": len(nutrition_sources),
    }


def seed(run_id: str, state_path: Path, *, confirm_write: bool) -> dict[str, Any]:
    if not confirm_write:
        raise RuntimeError("--confirm-write is required for the seed phase")
    repository = _repository()
    owner, food, encounter = _fixture(run_id)
    first = repository.save_encounter_idempotently(owner, food, encounter)
    if not first.get("inserted"):
        raise AssertionError("Acceptance run_id already exists; choose a new run_id")

    # A new repository instance models a fresh application process.
    restarted_repository = _repository()
    persisted = _assert_fixture(
        restarted_repository,
        {
            "owner_user_id": owner,
            "food_id": food["food_id"],
            "idempotency_key": encounter["idempotency_key"],
            "expected_usage_count": 1,
        },
    )
    duplicate = restarted_repository.save_encounter_idempotently(owner, food, encounter)
    if not duplicate.get("duplicate"):
        raise AssertionError("Repeated Encounter was not classified as duplicate")
    after_duplicate = _assert_fixture(
        restarted_repository,
        {
            "owner_user_id": owner,
            "food_id": food["food_id"],
            "idempotency_key": encounter["idempotency_key"],
            "expected_usage_count": 1,
        },
    )
    state = {
        "run_id": run_id,
        "owner_user_id": owner,
        "food_id": food["food_id"],
        "encounter_id": encounter["encounter_id"],
        "idempotency_key": encounter["idempotency_key"],
        "expected_usage_count": 1,
        "seeded_at": _utc_now(),
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "phase": "seed",
        "state_path": str(state_path),
        "first_inserted": True,
        "process_restart_check": persisted,
        "duplicate_skipped": True,
        "after_duplicate": after_duplicate,
    }


def verify(state_path: Path) -> dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    repository = _repository()
    return {"phase": "verify", "state_path": str(state_path), **_assert_fixture(repository, state)}


def cleanup(state_path: Path, *, confirm_write: bool) -> dict[str, Any]:
    if not confirm_write:
        raise RuntimeError("--confirm-write is required for cleanup")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    owner = str(state["owner_user_id"])
    if not owner.startswith(ACCEPTANCE_OWNER_PREFIX):
        raise RuntimeError("Cleanup is restricted to PR12 acceptance owners")
    repository = _repository()
    quoted_owner = parse.quote(owner, safe="")
    repository.client.request("DELETE", f"food_encounters?owner_user_id=eq.{quoted_owner}")
    repository.client.request("DELETE", f"foods?owner_user_id=eq.{quoted_owner}")
    return {"phase": "cleanup", "owner_user_id": owner, "deleted": True}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PR12 acceptance checks against a real Supabase project.")
    parser.add_argument("--phase", choices=("seed", "verify", "cleanup"), required=True)
    parser.add_argument("--run-id", default=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--confirm-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.phase == "seed":
            report = seed(args.run_id, args.state, confirm_write=args.confirm_write)
        elif args.phase == "verify":
            report = verify(args.state)
        else:
            report = cleanup(args.state, confirm_write=args.confirm_write)
    except Exception as exc:
        print(json.dumps({"phase": args.phase, "status": "failed", "error": type(exc).__name__}, indent=2))
        return 1
    print(json.dumps({"status": "passed", **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
