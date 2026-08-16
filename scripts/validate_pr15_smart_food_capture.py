from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from food_master_repository import JsonFoodMasterRepository  # noqa: E402
from food_resolver import build_food_knowledge_snapshot, resolve_food_text  # noqa: E402
from food_source_models import internal_nutrition_source  # noqa: E402
from personal_food_master import confirm_capture_food, remember_food_encounters_with_summary  # noqa: E402
from smart_food_capture import (  # noqa: E402
    calculate_daily_nutrition,
    canonical_builder_result,
    canonical_workout_from_text,
    candidates_from_resolution,
    default_capture_nutrition_basis,
    prepare_capture_item,
    search_food_candidates,
    unknown_candidate,
)


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "pr15_smart_food_capture.json"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def nutrition(value: dict) -> dict:
    return {
        "basis": value.get("basis") or "per_item",
        "calories_kcal": value.get("calories_kcal"),
        "protein_g": value.get("protein_g"),
        "fat_g": value.get("fat_g"),
        "carbs_g": value.get("carbs_g"),
        "sugar_g": None,
        "fiber_g": None,
        "salt_g": None,
    }


def confirmed_candidate(food: dict, *, raw_text: str | None = None) -> dict:
    candidate = unknown_candidate(raw_text or food["name"], "snacks")
    candidate.update(
        {
            "canonical_name": food["name"],
            "display_name": food["name"],
            "raw_text": raw_text or food["name"],
        }
    )
    return prepare_capture_item(
        candidate,
        meal_type="snacks",
        quantity=food.get("quantity") or 1,
        unit=food.get("unit"),
        consumed_quantity=food.get("quantity") or 1,
        nutrition=nutrition(food["nutrition"]),
        source_mode="user_label",
    )


def main() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    records_before = (ROOT / "records.csv").read_bytes()
    workout_history_before = (ROOT / "workout_history.py").read_bytes()

    with tempfile.TemporaryDirectory() as temp_dir:
        repository = JsonFoodMasterRepository(
            Path(temp_dir) / "personal_food_master.json",
            Path(temp_dir) / "food_encounters.jsonl",
        )
        user_id = "pr15-validation"
        stored_foods = []
        for food in fixture["confirmed_foods"]:
            candidate = confirmed_candidate(food, raw_text=food["aliases"][0])
            stored = confirm_capture_food(repository, user_id, candidate, now="2026-08-16T00:00:00+00:00")
            for alias in food["aliases"]:
                stored = repository.add_alias(user_id, stored["food_id"], alias)
            stored_foods.append(stored)

        knowledge = build_food_knowledge_snapshot(repository.list_foods(user_id))
        savas_resolution = resolve_food_text("SAVAS BIO", "snacks", knowledge=knowledge)
        check(savas_resolution["items"][0]["selected_origin"] == "personal", "SAVAS BIO reuses Personal Food Master")
        check(savas_resolution["items"][0]["total_nutrition"]["calories_kcal"] == 102, "confirmed SAVAS calories are reused")

        hostile_generic = {
            "food_id": "generic:savas-bio-pro-hostile",
            "brand": "SAVAS",
            "canonical_name": "SAVAS BIO PRO",
            "variant": None,
            "size": None,
            "aliases": ["SAVAS BIO", "SAVAS BIO PRO"],
            "nutrition": nutrition({"basis": "per_item", "calories_kcal": 999}),
            "source": internal_nutrition_source("legacy_dictionary", "pr15-hostile-estimate"),
        }
        priority_knowledge = build_food_knowledge_snapshot(
            repository.list_foods(user_id),
            generic_catalog=[hostile_generic],
        )
        priority_result = resolve_food_text("SAVAS BIO", "snacks", knowledge=priority_knowledge)
        check(priority_result["items"][0]["selected_origin"] == "personal", "Personal Food Master outranks Generic and Estimate")
        check(priority_result["kcal"] == 102, "confirmed food is never replaced by an estimate")

        explicit_result = resolve_food_text("SAVAS BIO 120kcal", "snacks", knowledge=priority_knowledge)
        check(explicit_result["items"][0]["selected_origin"] == "explicit", "current explicit nutrition outranks Personal Food Master")
        official_result = resolve_food_text("ファミチキ", "snacks", knowledge=build_food_knowledge_snapshot(generic_catalog=[]))
        check(official_result["items"][0]["selected_origin"] == "official", "Official Food outranks fallback")

        suggestions = search_food_candidates("SAV", knowledge)
        check(suggestions and suggestions[0]["source_type"] == "personal_master", "partial search prioritizes Personal Food Master")
        check(suggestions[0]["confidence"] == "high", "source-based confidence is deterministic")

        quantity_case = fixture["quantity_case"]
        dango = unknown_candidate(quantity_case["name"], "snacks")
        dango_item = prepare_capture_item(
            dango,
            meal_type="snacks",
            quantity=quantity_case["quantity"],
            unit=quantity_case["unit"],
            consumed_quantity=quantity_case["quantity"],
            nutrition=nutrition({"basis": "per_item", "calories_kcal": quantity_case["per_item_kcal"]}),
            source_mode="user_label",
        )
        dango_total = calculate_daily_nutrition([dango_item])
        check(dango_total["totals"]["calories_kcal"] == quantity_case["expected_kcal"], "quantity scaling multiplies per-item nutrition")

        planned = prepare_capture_item(
            dango,
            meal_type="snacks",
            quantity=3,
            unit="本",
            consumed_quantity=0,
            nutrition=nutrition({"basis": "per_item", "calories_kcal": 122}),
            source_mode="user_label",
        )
        check(calculate_daily_nutrition([planned])["consumed_count"] == 0, "purchased food is excluded from daily nutrition")
        partial = prepare_capture_item(
            planned,
            meal_type="snacks",
            quantity=3,
            unit="本",
            consumed_quantity=2,
            nutrition=planned["nutrition"],
            source_mode="candidate",
            capture_id=planned["capture_id"],
        )
        check(calculate_daily_nutrition([partial])["totals"]["calories_kcal"] == 244, "only consumed quantity is included")

        label_values = {
            "basis": "unknown",
            "calories_kcal": 122,
            "protein_g": 2.4,
            "fat_g": 0.6,
            "carbs_g": 27.5,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        }
        label_item = prepare_capture_item(
            unknown_candidate("PR15 TEST 団子", "snacks"),
            meal_type="snacks",
            quantity=3,
            unit="本",
            consumed_quantity=2,
            nutrition=label_values,
            source_mode="user_label",
        )
        check(default_capture_nutrition_basis("本") == "per_item", "discrete UI unit defaults to per-item basis")
        check(label_item["source_type"] == "user_label", "new label nutrition remains user-confirmed")
        check(label_item["nutrition"]["basis"] == "per_item", "new label nutrition receives a scalable basis")
        label_daily = calculate_daily_nutrition([label_item])
        check(
            label_daily["totals"]
            == {
                "calories_kcal": 244.0,
                "protein_g": 4.8,
                "fat_g": 1.2,
                "carbs_g": 55.0,
                "sugar_g": None,
                "fiber_g": None,
                "salt_g": None,
            },
            "three purchased and two consumed scales all entered nutrition",
        )
        check(label_daily["unknown_count"] == 0, "known label calories and macros are not unknown")
        label_builder = canonical_builder_result(
            {"date": "2026-08-16", "workout": {"performed": False, "exercises": []}},
            [label_item],
        )
        canonical_label = label_builder["canonical"]["meals"]["snacks"][0]
        check(label_builder["validation_passed"], "label capture Canonical record validates")
        check(label_builder["normalization_changes"] == [], "label capture Canonical record needs zero normalization")
        check(canonical_label["quantity"] == 2.0, "Canonical food quantity uses consumed quantity")
        check(canonical_label["nutrition"]["calories_kcal"] == 244.0, "Canonical calories use consumed total")
        check(canonical_label["nutrition"]["protein_g"] == 4.8, "Canonical protein uses consumed total")
        check(canonical_label["nutrition"]["fat_g"] == 1.2, "Canonical fat uses consumed total")
        check(canonical_label["nutrition"]["carbs_g"] == 55.0, "Canonical carbs use consumed total")

        saved_label = confirm_capture_food(
            repository,
            user_id,
            label_item,
            now="2026-08-16T02:00:00+00:00",
        )
        label_knowledge = build_food_knowledge_snapshot(repository.list_foods(user_id))
        label_suggestions = search_food_candidates("PR15 TEST 団子", label_knowledge)
        restored = label_suggestions[0]
        check(saved_label["status"] == "active", "confirmed label food is active in Personal Food Master")
        check(restored["source_type"] == "personal_master", "confirmed label food is restored from Personal Food Master")
        check(
            restored["nutrition"]
            == {
                "basis": "per_item",
                "calories_kcal": 122.0,
                "protein_g": 2.4,
                "fat_g": 0.6,
                "carbs_g": 27.5,
                "sugar_g": None,
                "fiber_g": None,
                "salt_g": None,
            },
            "re-search restores confirmed calories and PFC",
        )

        unknown = prepare_capture_item(
            unknown_candidate(fixture["unknown_case"]["name"], "breakfast"),
            meal_type="breakfast",
            quantity=1,
            unit=None,
            consumed_quantity=1,
        )
        unknown_total = calculate_daily_nutrition([unknown])
        check(unknown_total["totals"]["calories_kcal"] is None, "unknown food is not converted to zero kcal")
        check(unknown_total["unknown_count"] == 1, "unknown food remains visible in data quality")

        estimated = prepare_capture_item(
            unknown_candidate(fixture["estimated_case"]["name"], "lunch"),
            meal_type="lunch",
            quantity=1,
            unit=None,
            consumed_quantity=1,
            nutrition=nutrition({"basis": "total", "calories_kcal": 400}),
            source_mode="estimated",
        )
        check(estimated["source_type"] == "estimated" and estimated["confidence"] == "low", "manual estimate stays visibly estimated")
        try:
            confirm_capture_food(repository, user_id, estimated)
        except ValueError:
            pass
        else:
            raise AssertionError("estimated nutrition must not be promoted")
        print("PASS: estimated nutrition cannot be promoted to confirmed knowledge")

        edited = prepare_capture_item(
            dango_item,
            meal_type="snacks",
            quantity=2,
            unit="本",
            consumed_quantity=2,
            nutrition=nutrition({"basis": "per_item", "calories_kcal": 130}),
            source_mode="estimated",
            capture_id=dango_item["capture_id"],
        )
        check(calculate_daily_nutrition([edited])["totals"]["calories_kcal"] == 260, "food edit immediately recalculates daily total")

        savas_candidate = candidates_from_resolution(savas_resolution, "snacks")[0]
        savas_edited = prepare_capture_item(
            savas_candidate,
            meal_type="snacks",
            quantity=1,
            unit="本",
            consumed_quantity=1,
            nutrition=nutrition({"basis": "per_item", "calories_kcal": 105, "protein_g": 15, "fat_g": 0, "carbs_g": 11}),
            source_mode="user_label",
        )
        updated_food = confirm_capture_food(repository, user_id, savas_edited, now="2026-08-16T01:00:00+00:00")
        updated_knowledge = build_food_knowledge_snapshot(repository.list_foods(user_id))
        updated_resolution = resolve_food_text("SAVAS BIO", "snacks", knowledge=updated_knowledge)
        check(updated_food["status"] == "active", "approved edit persists as active Personal Food")
        check(updated_resolution["kcal"] == 105, "next lookup returns the approved edited value")

        oikos_resolution = resolve_food_text("OIKOS PRO", "snacks", knowledge=updated_knowledge)
        check(oikos_resolution["items"][0]["selected_origin"] == "personal", "approved OIKOS alias resolves to Personal Food Master")

        daily_state = {
            "date": "2026-08-16",
            "weight": 83.2,
            "sleep_hours": 7.5,
            "condition": 8,
            "steps": 10000,
            "mode": "NORMAL",
            "alcohol_consumed": True,
            "alcohol_detail": fixture["alcohol_detail"],
            "alcohol_level": "軽い",
            "workout": canonical_workout_from_text(True, "ベンチプレス 90kg×5×4"),
            "notes": "PR15 fixture",
        }
        original_daily = deepcopy(daily_state)
        original_items = deepcopy([partial, unknown, estimated])
        builder = canonical_builder_result(daily_state, [partial, unknown, estimated])
        check(builder["validation_passed"], "Canonical Builder output validates against Schema 1.0")
        check(builder["normalization_changes"] == [], "UI-generated Canonical JSON requires zero normalization")
        check(daily_state == original_daily and [partial, unknown, estimated] == original_items, "Canonical Builder does not mutate input")
        projected_count = sum(len(values) for values in builder["canonical"]["meals"].values())
        check(projected_count == 3 and len(builder["canonical"]["meals"]["snacks"]) == 1, "consumed foods are projected to their Canonical meal types")

        deduplicated = calculate_daily_nutrition([partial, partial])
        check(deduplicated["totals"]["calories_kcal"] == 244, "daily nutrition does not double count a capture id")

        parsed = savas_resolution["parsed_foods"]
        first_save = remember_food_encounters_with_summary(
            repository,
            user_id,
            parsed,
            meal_type="snacks",
            record_date="2026-08-16",
            operation_id="pr15-idempotency",
            resolution=updated_resolution,
        )
        second_save = remember_food_encounters_with_summary(
            repository,
            user_id,
            parsed,
            meal_type="snacks",
            record_date="2026-08-16",
            operation_id="pr15-idempotency",
            resolution=updated_resolution,
        )
        check(first_save["saved"] == 1 and second_save["duplicates"] == 1, "Food Encounter idempotency remains intact")
        check(len(repository.list_encounters(user_id)) == 1, "duplicate encounter is not appended")

    check((ROOT / "records.csv").read_bytes() == records_before, "validation does not modify records.csv")
    check((ROOT / "workout_history.py").read_bytes() == workout_history_before, "validation does not modify Workout history")
    protected = subprocess.run(
        ["git", "diff", "--exit-code", "main", "--", "records.csv", "workout_history.py", "schemas/bodyos-daily-log.schema.json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    check(protected.returncode == 0, "records.csv, Workout history, and Schema 1.0 are unchanged from main")
    print("PR15 Smart Food Capture validation passed.")


if __name__ == "__main__":
    main()
