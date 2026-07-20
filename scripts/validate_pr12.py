from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, unquote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from food_master_models import new_food_record
from food_master_repository import JsonFoodMasterRepository
from food_parser import parse_food_text
from food_repository_factory import (
    FallbackFoodMasterRepository,
    UnavailableFoodMasterRepository,
    create_food_master_repository,
)
from food_resolver import build_food_knowledge_snapshot, resolve_food_text
from personal_food_master import remember_food_encounters_with_summary
from scripts.migrate_food_knowledge_to_supabase import build_migration_report
from supabase_food_master_repository import SupabaseFoodMasterRepository


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.foods: dict[str, dict] = {}
        self.aliases: dict[tuple[str, str], dict] = {}
        self.sources: dict[str, dict] = {}
        self.facts: dict[str, dict] = {}
        self.encounters: dict[tuple[str, str], dict] = {}

    @staticmethod
    def _matches(row: dict, query: dict[str, list[str]]) -> bool:
        for key, values in query.items():
            if key in {"select", "order", "limit", "on_conflict"}:
                continue
            expression = unquote(values[0])
            if expression.startswith("eq.") and str(row.get(key) or "") != expression[3:]:
                return False
            if expression.startswith("neq.") and str(row.get(key) or "") == expression[4:]:
                return False
            if expression.startswith("in.("):
                allowed = expression[4:-1].split(",")
                if str(row.get(key) or "") not in allowed:
                    return False
        return True

    def _persist_food(self, owner: str, payload: dict, *, increment: bool) -> dict:
        row = deepcopy(payload["food"])
        food_id = str(row["food_id"])
        identity = str(row.get("identity_key") or "")
        existing_identity = next(
            (
                food
                for food in self.foods.values()
                if food.get("owner_user_id") == owner
                and food.get("identity_key") == identity
                and food.get("status") != "archived"
            ),
            None,
        )
        if existing_identity is not None:
            food_id = str(existing_identity["food_id"])
            row["food_id"] = food_id
        existing = self.foods.get(food_id)
        if increment:
            count = int((existing or {}).get("usage_count", 0)) + 1
            row["usage_count"] = count
            row["use_count"] = count
        self.foods[food_id] = {**(existing or {}), **row, "owner_user_id": owner}
        for alias in payload.get("aliases") or []:
            alias_row = {**deepcopy(alias), "food_id": food_id, "owner_user_id": owner}
            self.aliases[(food_id, str(alias_row["normalized_alias"]))] = alias_row
        for source in payload.get("nutrition_sources") or []:
            self.sources[str(source["source_id"])] = {**deepcopy(source), "food_id": food_id}
        for fact in payload.get("nutrition_facts") or []:
            key = f"{fact.get('source_id')}:{fact.get('basis')}"
            self.facts[key] = {**deepcopy(fact), "nutrition_fact_id": key, "food_id": food_id}
        return deepcopy(self.foods[food_id])

    def request(self, method: str, path: str, *, payload=None, prefer=None):
        table, _, query_string = path.partition("?")
        query = parse_qs(query_string)
        if table == "rpc/upsert_food_knowledge_v1":
            food = self._persist_food(payload["p_owner_user_id"], payload["p_food_payload"], increment=False)
            return {"food": food}
        if table == "rpc/save_food_encounter_v1":
            owner = payload["p_owner_user_id"]
            encounter = deepcopy(payload["p_encounter"])
            key = (owner, str(encounter["idempotency_key"]))
            if key in self.encounters:
                stored = self.encounters[key]
                return {"inserted": False, "food": self.foods.get(stored["resolved_food_id"]), "encounter": stored}
            food = self._persist_food(owner, payload["p_food_payload"], increment=True)
            encounter["owner_user_id"] = owner
            encounter["resolved_food_id"] = food["food_id"]
            self.encounters[key] = encounter
            return {"inserted": True, "food": food, "encounter": encounter}
        tables = {
            "foods": self.foods,
            "food_aliases": self.aliases,
            "nutrition_sources": self.sources,
            "nutrition_facts": self.facts,
            "food_encounters": self.encounters,
        }
        if method == "POST" and table == "food_encounters":
            owner = str(payload["owner_user_id"])
            key = (owner, str(payload["idempotency_key"]))
            if key in self.encounters:
                return []
            self.encounters[key] = deepcopy(payload)
            return [deepcopy(payload)]
        rows = [deepcopy(row) for row in tables[table].values() if self._matches(row, query)]
        order = query.get("order", [""])[0]
        if order:
            fields = [part.split(".")[0] for part in order.split(",")]
            rows.sort(key=lambda row: tuple(str(row.get(field) or "") for field in fields), reverse="desc" in order)
        if "limit" in query:
            rows = rows[: int(query["limit"][0])]
        return rows


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def validation_food() -> dict:
    parsed = parse_food_text("ファミマ ファミチキ", "昼")
    return new_food_record("user-a", parsed["items"][0], now="2026-07-20T00:00:00+00:00")


def main() -> None:
    records_before = (ROOT / "records.csv").read_bytes()
    fake = FakeSupabaseClient()
    supabase = SupabaseFoodMasterRepository(fake)
    supabase.health_check()

    food = validation_food()
    food["aliases"].append("いつものチキン")
    stored = supabase.upsert_food("user-a", food)
    assert_equal(stored["food_id"], food["food_id"], "Supabase upsert")
    assert_equal(supabase.find_by_alias("user-a", "いつものチキン")[0]["food_id"], food["food_id"], "alias query")

    json_snapshot = build_food_knowledge_snapshot([food])
    supabase_snapshot = build_food_knowledge_snapshot(supabase.list_foods("user-a"))
    json_result = resolve_food_text("いつものチキン", "昼", knowledge=json_snapshot)
    supabase_result = resolve_food_text("いつものチキン", "昼", knowledge=supabase_snapshot)
    assert_equal(supabase_result["kcal"], json_result["kcal"], "resolver repository parity")
    assert_equal(supabase_result["resolution_counts"], json_result["resolution_counts"], "resolver origins parity")

    parsed = parse_food_text("おばあちゃん特製カレー", "夜")
    resolution = resolve_food_text(parsed["raw_text"], "夜", knowledge=build_food_knowledge_snapshot([]))
    original_parsed = deepcopy(parsed)
    first = remember_food_encounters_with_summary(
        supabase,
        "user-b",
        parsed,
        meal_type="夜",
        record_date="2026-07-20",
        operation_id="manual:content-a",
        used_at="2026-07-20T10:00:00+00:00",
        resolution=resolution,
    )
    retry = remember_food_encounters_with_summary(
        supabase,
        "user-b",
        parsed,
        meal_type="夜",
        record_date="2026-07-20",
        operation_id="manual:content-a",
        used_at="2026-07-20T10:00:00+00:00",
        resolution=resolution,
    )
    assert_equal(first["saved"], 1, "first encounter saved")
    assert_equal(retry["duplicates"], 1, "retry skipped")
    assert_equal(len(supabase.list_encounters("user-b")), 1, "one encounter after retry")
    assert_equal(supabase.list_foods("user-b")[0]["usage_count"], 1, "usage count after retry")
    assert_equal(parsed, original_parsed, "parser input remains immutable")

    changed = remember_food_encounters_with_summary(
        supabase,
        "user-b",
        parsed,
        meal_type="夜",
        record_date="2026-07-20",
        operation_id="manual:content-b",
        used_at="2026-07-20T11:00:00+00:00",
        resolution=resolution,
    )
    assert_equal(changed["saved"], 1, "changed content identity saved")
    assert_equal(supabase.list_foods("user-b")[0]["usage_count"], 2, "usage count changed content")

    with TemporaryDirectory() as directory:
        root = Path(directory)
        local = JsonFoodMasterRepository(root / "master.json", root / "encounters.jsonl")
        json_only = create_food_master_repository({}, local)
        assert_equal(type(json_only).__name__, "JsonFoodMasterRepository", "missing secrets default")
        fallback = create_food_master_repository({"FOOD_KNOWLEDGE_REPOSITORY": "supabase"}, local)
        if not isinstance(fallback, FallbackFoodMasterRepository):
            raise AssertionError("Supabase missing secrets must use JSON fallback")
        strict = create_food_master_repository(
            {"FOOD_KNOWLEDGE_REPOSITORY": "supabase", "FOOD_KNOWLEDGE_MODE": "strict_supabase"},
            local,
        )
        if not isinstance(strict, UnavailableFoodMasterRepository):
            raise AssertionError("strict mode must remain startup-safe")

        empty_report = build_migration_report(root / "missing.json", root / "missing.jsonl", "user-a")
        assert_equal(empty_report["source"]["foods"], 0, "missing migration source foods")
        assert_equal(empty_report["source"]["encounters"], 0, "missing migration source encounters")

        local.upsert_food("user-a", food)
        encounter = {
            "encounter_id": "enc_migration",
            "idempotency_key": "migration-key",
            "owner_user_id": "user-a",
            "user_id": "legacy-compatibility-field",
            "record_date": "2026-07-20",
            "resolved_food_id": food["food_id"],
            "created_at": "2026-07-20T00:00:00+00:00",
            "schema_version": "1.1",
        }
        local.append_encounter("user-a", encounter)
        migration_target = SupabaseFoodMasterRepository(FakeSupabaseClient())
        applied = build_migration_report(
            local.master_path,
            local.encounters_path,
            "user-a",
            target=migration_target,
            apply=True,
        )
        rerun = build_migration_report(
            local.master_path,
            local.encounters_path,
            "user-a",
            target=migration_target,
            apply=True,
        )
        assert_equal(applied["result"]["encounters_saved"], 1, "migration first apply")
        assert_equal(rerun["result"]["duplicates_skipped"], 1, "migration rerun idempotency")
        assert_equal(rerun["target_after"]["encounters"], 1, "migration count reconciliation")
        migrated = migration_target.list_encounters("user-a")[0]
        if "user_id" in migrated:
            raise AssertionError("legacy Encounter fields must not reach PostgREST")

    sql = (ROOT / "supabase/migrations/20260720_food_knowledge.sql").read_text(encoding="utf-8")
    required_sql = [
        "unique (owner_user_id, idempotency_key)",
        "save_food_encounter_v1",
        "idempotency_key is required",
        "hashtextextended(p_owner_user_id || '|' || (p_encounter ->> 'idempotency_key'), 1)",
        "row level security",
        "auth.uid()",
        "on delete cascade",
        "foods_personal_identity_active_uidx",
        "grant select on public.foods",
    ]
    for requirement in required_sql:
        if requirement not in sql.lower():
            raise AssertionError(f"SQL contract missing: {requirement}")

    assert_equal((ROOT / "records.csv").read_bytes(), records_before, "records.csv unchanged")
    print("PR12 Food Knowledge Supabase Migration validation passed")


if __name__ == "__main__":
    main()
