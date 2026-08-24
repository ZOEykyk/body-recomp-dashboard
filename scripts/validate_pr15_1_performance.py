from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Any, Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from food_master_repository import JsonFoodMasterRepository  # noqa: E402
from food_knowledge_diagnostics import (  # noqa: E402
    FOOD_KNOWLEDGE_DIAGNOSTICS_VERSION,
    confirmed_save_diagnostics,
    food_knowledge_user_key,
    repository_runtime_diagnostics,
)
from food_repository_factory import FallbackFoodMasterRepository  # noqa: E402
from food_resolver import build_food_knowledge_snapshot, resolve_food_text  # noqa: E402
from food_source_models import internal_nutrition_source  # noqa: E402
from dashboard import prepare_dashboard_projection  # noqa: E402
from nutrition_intelligence import analyze_nutrition  # noqa: E402
from personal_food_master import confirm_capture_food  # noqa: E402
from scripts.validate_pr12 import FakeSupabaseClient  # noqa: E402
from smart_food_capture import (  # noqa: E402
    calculate_daily_nutrition,
    canonical_builder_result,
    prepare_capture_item,
    search_food_candidates,
    search_food_candidates_with_diagnostics,
    unknown_candidate,
)
from workout_intelligence import analyze_workout  # noqa: E402
from supabase_food_master_repository import SupabaseFoodMasterRepository  # noqa: E402


ITERATIONS = 25
WARMUPS = 3
EXPECTED_CANONICAL_SHA256 = "7efc99d403fe5b1424f4ed10c2e9eb9f59d9d8844938cc021405b72971c82afb"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def benchmark(function: Callable[[], Any], *, iterations: int = ITERATIONS) -> dict[str, float]:
    for _ in range(WARMUPS):
        function()
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        function()
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    percentile_index = min(round(0.95 * (len(ordered) - 1)), len(ordered) - 1)
    return {
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[percentile_index], 3),
        "min_ms": round(min(samples), 3),
    }


def nutrition_source(index: int) -> dict[str, Any]:
    return {
        "source": internal_nutrition_source(
            "user_verified",
            f"performance-source-{index}",
        ),
        "nutrition": {
            "basis": "per_item",
            "calories_kcal": 100 + index % 50,
            "protein_g": 10.0,
            "fat_g": 2.0,
            "carbs_g": 12.0,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        },
    }


def personal_food(index: int, user_id: str) -> dict[str, Any]:
    return {
        "food_id": f"performance-food-{index}",
        "owner_user_id": user_id,
        "user_id": user_id,
        "scope": "personal",
        "brand": "Performance",
        "canonical_name": f"テスト食品{index}",
        "variant": None,
        "size": None,
        "category": "validation",
        "default_quantity": 1,
        "default_unit": "個",
        "aliases": [f"性能食品{index}", f"test food {index}"],
        "alias_metadata": [],
        "nutrition_sources": [nutrition_source(index)],
        "status": "active",
        "review_status": "reviewed",
        "usage_count": index,
        "use_count": index,
        "last_used_at": "2026-08-16T00:00:00+00:00",
        "created_at": "2026-08-01T00:00:00+00:00",
        "updated_at": "2026-08-16T00:00:00+00:00",
        "schema_version": "1.1",
        "created_by": "performance-validator",
        "updated_by": "performance-validator",
    }


def capture_items() -> list[dict[str, Any]]:
    items = []
    for index in range(11):
        candidate = unknown_candidate(f"計測食品{index}", "snacks")
        items.append(
            prepare_capture_item(
                candidate,
                meal_type=("breakfast", "lunch", "snacks", "dinner")[index % 4],
                quantity=3 if index == 0 else 1,
                unit="本" if index == 0 else "個",
                consumed_quantity=2 if index == 0 else 1,
                nutrition={
                    "basis": "per_item",
                    "calories_kcal": 122 + index,
                    "protein_g": 2.4,
                    "fat_g": 0.6,
                    "carbs_g": 27.5,
                    "sugar_g": None,
                    "fiber_g": None,
                    "salt_g": None,
                },
                source_mode="user_label",
                capture_id=f"performance-capture-{index}",
            )
        )
    return items


def confirmed_label_item(name: str) -> dict[str, Any]:
    return prepare_capture_item(
        unknown_candidate(name, "snacks"),
        meal_type="snacks",
        quantity=1,
        unit="本",
        consumed_quantity=1,
        nutrition={
            "basis": "per_item",
            "calories_kcal": 99,
            "protein_g": 3.0,
            "fat_g": 0.5,
            "carbs_g": 13.0,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        },
        source_mode="user_label",
    )


def cached_knowledge(
    repository: Any,
    user_id: str,
    cache: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    key = (user_id, repository.cache_revision())
    if key not in cache:
        snapshot = repository.build_snapshot(user_id)
        cache[key] = build_food_knowledge_snapshot(snapshot["personal_foods"])
    return cache[key]


def validate_immediate_confirmed_search(repository: Any, label: str) -> tuple[int, int, dict[str, Any]]:
    user_id = f"immediate-{label}"
    name = "PR15.1テスト バナナ②"
    cache: dict[tuple[str, int], dict[str, Any]] = {}
    check(not search_food_candidates(name, cached_knowledge(repository, user_id, cache)), f"{label}: initial search miss")
    revision_before = repository.cache_revision()
    stored_food = confirm_capture_food(
        repository,
        user_id,
        confirmed_label_item(name),
        now="2026-08-17T00:00:00+00:00",
    )
    revision_after = repository.cache_revision()
    check(revision_after == revision_before + 1, f"{label}: confirmed save increments revision")
    knowledge = cached_knowledge(repository, user_id, cache)
    stored = [food for food in knowledge["personal_foods"] if food.get("canonical_name") == name]
    check(len(stored) == 1 and stored[0].get("status") == "active", f"{label}: next snapshot contains active food")
    check(len(stored[0].get("nutrition_sources") or []) == 1, f"{label}: snapshot retains nutrition source")
    matches, search_diagnostics = search_food_candidates_with_diagnostics(name, knowledge)
    check(bool(matches), f"{label}: immediate search hit without TTL wait")
    match = matches[0]
    check(match["source_type"] == "personal_master", f"{label}: search returns Personal Food Master")
    check(match["source_detail"] == "過去の確認値" and match["confidence"] == "high", f"{label}: confirmed presentation restored")
    check(
        match["nutrition"]
        == {
            "basis": "per_item",
            "calories_kcal": 99.0,
            "protein_g": 3.0,
            "fat_g": 0.5,
            "carbs_g": 13.0,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        },
        f"{label}: calories and P/F/C restored",
    )
    cloud_food = deepcopy(stored[0])
    cloud_source = cloud_food["nutrition_sources"][0]["source"]
    cloud_source["captured_at"] = "2026-08-17T00:00:00+00:00"
    cloud_source["verified_at"] = "2026-08-17T00:00:00+00:00"
    cloud_matches, cloud_diagnostics = search_food_candidates_with_diagnostics(
        name,
        build_food_knowledge_snapshot([cloud_food]),
    )
    check(bool(cloud_matches), f"{label}: Supabase timestamptz source remains searchable")
    check(
        cloud_diagnostics["personal_trace"][0]["source_selection_status"] == "selected",
        f"{label}: Supabase timestamptz source is selected",
    )
    check(
        cloud_diagnostics["personal_trace"][0]["drop_reason"] == "included",
        f"{label}: Supabase timestamptz source is not dropped",
    )
    check(search_diagnostics["personal_name_match_count"] == 1, f"{label}: diagnostics observe name match")
    check(search_diagnostics["personal_source_selected_count"] == 1, f"{label}: diagnostics observe selected source")
    check(
        search_diagnostics["personal_trace"][0]["drop_reason"] == "included",
        f"{label}: diagnostics observe candidate inclusion",
    )
    save_diagnostics = confirmed_save_diagnostics(
        repository,
        user_id,
        stored_food,
        revision_before=revision_before,
    )
    check(save_diagnostics["food_id"] == stored_food["food_id"], f"{label}: diagnostics retain stored food_id")
    check(save_diagnostics["post_save_snapshot_contains_food"], f"{label}: diagnostics verify persisted snapshot")
    check(save_diagnostics["snapshot_status"] == "active", f"{label}: diagnostics expose active status")
    check(
        save_diagnostics["snapshot_selection"]["selected_source_type"] == "explicit_user_label",
        f"{label}: diagnostics expose selected source type",
    )
    runtime_diagnostics = repository_runtime_diagnostics(
        repository,
        user_id,
        knowledge,
        cached_personal_food_count=len(knowledge["personal_foods"]),
    )
    check(runtime_diagnostics["cache_revision"] == revision_after, f"{label}: runtime diagnostics expose revision")
    check(
        runtime_diagnostics["diagnostics_version"] == FOOD_KNOWLEDGE_DIAGNOSTICS_VERSION,
        f"{label}: Cloud diagnostics expose their build version",
    )
    check(runtime_diagnostics["source_revision"] != "unavailable", f"{label}: deployed source revision is observable")
    check(
        runtime_diagnostics["cached_personal_food_count"] == runtime_diagnostics["knowledge_personal_food_count"] == 1,
        f"{label}: cached and active knowledge counts are observable",
    )
    check(
        runtime_diagnostics["user_key"] == food_knowledge_user_key(user_id),
        f"{label}: save/search user identity is comparable without raw ID",
    )
    diagnostic_text = json.dumps(
        {"save": save_diagnostics, "runtime": runtime_diagnostics, "search": search_diagnostics},
        ensure_ascii=False,
        sort_keys=True,
    )
    check(user_id not in diagnostic_text and name not in diagnostic_text, f"{label}: diagnostics omit raw identity and name")
    check(
        not any(field in diagnostic_text for field in ("calories_kcal", "protein_g", "fat_g", "carbs_g")),
        f"{label}: diagnostics omit nutrition values",
    )
    return revision_before, revision_after, match


def main() -> None:
    records_before = (ROOT / "records.csv").read_bytes()
    user_id = "performance-validator"
    foods = [personal_food(index, user_id) for index in range(100)]
    items = capture_items()
    daily = {
        "date": "2026-08-16",
        "weight": 83.2,
        "sleep_hours": 8,
        "condition": 8,
        "steps": 11786,
        "workout": {"performed": False, "exercises": []},
        "notes": "performance validation",
        "mode": "NORMAL",
    }
    workout_record = {
        "日付": "2026-07-02",
        "筋トレ有無": "あり",
        "筋トレ内容": "ベンチプレス 90kg×5×4、85kg×6\n懸垂 10,10,8,8\nバーベルスクワット 95kg 7,7,7,8",
    }
    nutrition_record = canonical_builder_result(daily, items)["canonical"]
    historical_records = pd.read_csv(ROOT / "records.csv").to_dict("records")

    with tempfile.TemporaryDirectory() as temp_dir:
        repository = JsonFoodMasterRepository(
            Path(temp_dir) / "personal_food_master.json",
            Path(temp_dir) / "food_encounters.jsonl",
        )
        for food in foods:
            repository.upsert_food(user_id, food)
        knowledge = build_food_knowledge_snapshot(repository.list_foods(user_id))

        measurements = {
            "repository_snapshot": benchmark(lambda: repository.build_snapshot(user_id)),
            "knowledge_snapshot": benchmark(lambda: build_food_knowledge_snapshot(foods)),
            "warm_food_search": benchmark(lambda: search_food_candidates("性能食品9", knowledge)),
            "food_resolution": benchmark(lambda: resolve_food_text("性能食品9", "snacks", knowledge=knowledge)),
            "daily_nutrition": benchmark(lambda: calculate_daily_nutrition(items)),
            "canonical_builder": benchmark(lambda: canonical_builder_result(daily, items)),
            "nutrition_intelligence": benchmark(
                lambda: analyze_nutrition(nutrition_record, history=[], food_knowledge=knowledge)
            ),
            "nutrition_intelligence_full_history": benchmark(
                lambda: analyze_nutrition(
                    historical_records[-1],
                    history=historical_records[:-1],
                    food_knowledge=knowledge,
                ),
                iterations=10,
            ),
            "workout_intelligence": benchmark(lambda: analyze_workout(workout_record, history=[])),
            "csv_read": benchmark(lambda: pd.read_csv(ROOT / "records.csv")),
            "rerun_shared_food_knowledge": benchmark(
                lambda: build_food_knowledge_snapshot(repository.build_snapshot(user_id)["personal_foods"]),
                iterations=10,
            ),
            "static_catalog_retrieval": benchmark(
                lambda: (knowledge["official_catalog"], knowledge["generic_catalog"]),
            ),
            "food_edit": benchmark(
                lambda: repository.upsert_food(user_id, foods[0]),
                iterations=10,
            ),
        }

        search_result = search_food_candidates("性能食品9", knowledge)
        check(bool(search_result), "warm search returns candidates")
        check(search_result[0]["source_type"] == "personal_master", "personal result retains priority")
        canonical = canonical_builder_result(daily, items)
        check(canonical["validation_passed"], "Canonical Schema validation remains mandatory")
        check(
            canonical["nutrition"]["included_items"][0]["calculation"]["calories_kcal"] == 244,
            "3 purchased / 2 consumed scaling remains correct",
        )
        check(canonical["nutrition"]["totals"]["calories_kcal"] == 1519, "daily nutrition total is deterministic")
        canonical_text = json.dumps(
            canonical["canonical"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        check(
            hashlib.sha256(canonical_text.encode("utf-8")).hexdigest() == EXPECTED_CANONICAL_SHA256,
            "Canonical output is byte-stable against the pre-optimization fixture",
        )
        original_knowledge = deepcopy(knowledge)
        resolve_food_text("性能食品9", "snacks", knowledge=knowledge)
        check(knowledge == original_knowledge, "resolver does not mutate Food Knowledge input")
        revision_before = repository.cache_revision()
        repository.upsert_food(user_id, {**foods[0], "notes": "cache invalidation"})
        check(repository.cache_revision() == revision_before + 1, "successful write invalidates cached personal snapshot")
        repository.upsert_food("second-user", personal_food(999, "second-user"))
        check(
            all(food["owner_user_id"] == user_id for food in repository.list_foods(user_id)),
            "personal cache source remains isolated by owner_user_id",
        )
        check(repository.list_foods("missing-user") == [], "unknown user cannot receive another user's Food Knowledge")
        inactive_food = personal_food(1001, user_id)
        inactive_food.update({"canonical_name": "診断対象食品", "status": "archived"})
        source_missing_food = personal_food(1002, user_id)
        source_missing_food.update({"canonical_name": "診断対象食品", "nutrition_sources": []})
        malformed_source_food = personal_food(1003, user_id)
        malformed_source_food.update(
            {
                "canonical_name": "診断対象食品",
                "nutrition_sources": [
                    {"source": None, "nutrition": {"basis": "per_item", "calories_kcal": 99}}
                ],
            }
        )
        _, drop_diagnostics = search_food_candidates_with_diagnostics(
            "診断対象食品",
            build_food_knowledge_snapshot([inactive_food, source_missing_food, malformed_source_food]),
        )
        drop_reasons = {trace["food_id"]: trace["drop_reason"] for trace in drop_diagnostics["personal_trace"]}
        check(
            drop_reasons[inactive_food["food_id"]] == "inactive",
            "search diagnostics identify inactive Personal Food drop",
        )
        check(
            drop_reasons[source_missing_food["food_id"]] == "source_not_selected",
            "search diagnostics identify nutrition source selection drop",
        )
        malformed_trace = next(
            trace
            for trace in drop_diagnostics["personal_trace"]
            if trace["food_id"] == malformed_source_food["food_id"]
        )
        check(
            malformed_trace["drop_reason"] == "source_not_selected"
            and malformed_trace["source_types"] == ["unknown"],
            "malformed persisted source metadata is diagnosed without crashing search",
        )
        dashboard_data = pd.read_csv(ROOT / "records.csv")
        dashboard_data["日付"] = pd.to_datetime(dashboard_data["日付"], errors="coerce")
        _, projection_before, _, _ = prepare_dashboard_projection(dashboard_data, "2026-08-17")
        changed_dashboard_data = dashboard_data.copy()
        changed_dashboard_data.loc[changed_dashboard_data.index[-1], "歩数"] = 12000
        _, projection_after, _, _ = prepare_dashboard_projection(changed_dashboard_data, "2026-08-17")
        check(projection_before["steps"] != 12000, "dashboard fixture starts with the stored steps value")
        check(projection_after["steps"] == 12000, "changed records bypass stale dashboard cache immediately")

        immediate_results: dict[str, dict[str, Any]] = {}
        immediate_json = JsonFoodMasterRepository(
            Path(temp_dir) / "immediate-foods.json",
            Path(temp_dir) / "immediate-encounters.jsonl",
        )
        before, after, match = validate_immediate_confirmed_search(immediate_json, "json")
        immediate_results["json"] = {"revision_before": before, "revision_after": after, "source_type": match["source_type"]}

        immediate_supabase = SupabaseFoodMasterRepository(FakeSupabaseClient())
        before, after, match = validate_immediate_confirmed_search(immediate_supabase, "supabase")
        immediate_results["supabase"] = {"revision_before": before, "revision_after": after, "source_type": match["source_type"]}

        switching_client = FakeSupabaseClient()
        switching_primary = SupabaseFoodMasterRepository(switching_client)
        switching_fallback = FallbackFoodMasterRepository(
            switching_primary,
            JsonFoodMasterRepository(
                Path(temp_dir) / "fallback-foods.json",
                Path(temp_dir) / "fallback-encounters.jsonl",
            ),
        )
        confirm_capture_food(
            switching_fallback,
            "revision-seed-user",
            confirmed_label_item("revision seed"),
            now="2026-08-17T00:00:00+00:00",
        )
        original_request = switching_client.request

        def fail_primary_write(method: str, path: str, *, payload: Any = None, prefer: Any = None) -> Any:
            if method == "POST" and path.startswith("rpc/upsert_food_knowledge_v1"):
                raise RuntimeError("intentional primary write failure")
            return original_request(method, path, payload=payload, prefer=prefer)

        switching_client.request = fail_primary_write
        before, after, match = validate_immediate_confirmed_search(switching_fallback, "fallback-switch")
        immediate_results["fallback_switch"] = {
            "revision_before": before,
            "revision_after": after,
            "source_type": match["source_type"],
        }

    check((ROOT / "records.csv").read_bytes() == records_before, "records.csv unchanged")
    result = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "iterations": ITERATIONS,
            "warmups": WARMUPS,
        },
        "dataset": {
            "records_rows": len(historical_records),
            "records_physical_lines": max(
                sum(1 for _ in (ROOT / "records.csv").open(encoding="utf-8-sig")) - 1,
                0,
            ),
            "personal_foods": len(foods),
            "capture_items": len(items),
        },
        "measurements": measurements,
        "immediate_confirmed_search": immediate_results,
    }
    print("PERFORMANCE_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
