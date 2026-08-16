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
from food_resolver import build_food_knowledge_snapshot, resolve_food_text  # noqa: E402
from food_source_models import internal_nutrition_source  # noqa: E402
from dashboard import prepare_dashboard_projection  # noqa: E402
from nutrition_intelligence import analyze_nutrition  # noqa: E402
from smart_food_capture import (  # noqa: E402
    calculate_daily_nutrition,
    canonical_builder_result,
    prepare_capture_item,
    search_food_candidates,
    unknown_candidate,
)
from workout_intelligence import analyze_workout  # noqa: E402


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
        dashboard_data = pd.read_csv(ROOT / "records.csv")
        dashboard_data["日付"] = pd.to_datetime(dashboard_data["日付"], errors="coerce")
        _, projection_before, _, _ = prepare_dashboard_projection(dashboard_data, "2026-08-17")
        changed_dashboard_data = dashboard_data.copy()
        changed_dashboard_data.loc[changed_dashboard_data.index[-1], "歩数"] = 12000
        _, projection_after, _, _ = prepare_dashboard_projection(changed_dashboard_data, "2026-08-17")
        check(projection_before["steps"] != 12000, "dashboard fixture starts with the stored steps value")
        check(projection_after["steps"] == 12000, "changed records bypass stale dashboard cache immediately")

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
    }
    print("PERFORMANCE_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
