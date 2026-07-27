from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyos_import import (  # noqa: E402
    ImportValidationError,
    canonical_to_projection,
    detect_anomalies,
    export_projection,
    import_fingerprint,
    normalize_import_document,
    preview_import,
    resolve_record_nutrition,
    workout_counts,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    csv_path = ROOT / "records.csv"
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    fixture = json.loads((ROOT / "tests/fixtures/pr13_acceptance_2026-07-26.json").read_text(encoding="utf-8"))
    original = deepcopy(fixture)

    document = normalize_import_document(fixture)
    record = document["records"][0]
    counts = workout_counts(record["workout"])
    check(record["weight"] == 83.2, "acceptance weight")
    check(record["sleep"]["hours"] == 8, "acceptance sleep")
    check(record["condition"] == 8, "acceptance condition")
    check(record["steps"] == 11786, "acceptance steps")
    check(sum(len(items) for items in record["meals"].values()) == 4, "four meal sections")
    check(counts["session_count"] == 1, "one workout session")
    check(counts["exercise_count"] == 6, "six exercises")
    check(counts["set_count"] == 20, "all listed sets are retained (spec text says 19, listed reps total 20)")
    check(record["workout"]["duration_minutes"] == 75, "75 minute workout")
    check(fixture == original, "input object is not mutated")

    resolver_calls: list[tuple[str, str]] = []

    def fallback_only(text: str, meal_type: str) -> dict:
        resolver_calls.append((text, meal_type))
        return {
            "items": [
                {
                    "selected_origin": "fallback",
                    "total_nutrition": {"calories_kcal": 999, "basis": "total"},
                }
            ]
        }

    nutrition = resolve_record_nutrition(record, fallback_only)
    check(nutrition["totals"]["calories_kcal"] == 2200, "explicit item calories are summed once")
    check(not resolver_calls, "resolver is not called for explicit item nutrition")
    check(nutrition["unknown_calorie_count"] == 0, "fully explicit fixture has no unknown calories")

    compatibility_fixture = json.loads(
        (ROOT / "tests/fixtures/pr13_compatibility_input_2026-07-26.json").read_text(encoding="utf-8")
    )
    compatibility_original = deepcopy(compatibility_fixture)
    compatibility_document = normalize_import_document(compatibility_fixture)
    compatibility_record = compatibility_document["records"][0]
    compatibility_nutrition = resolve_record_nutrition(
        compatibility_record,
        lambda text, meal_type: {"items": []},
    )
    check(not compatibility_document["warnings"], "compatible Schema 1.0 aliases do not create false warnings")
    check(
        sum(len(items) for items in compatibility_record["meals"].values()) == 11,
        "singular snack key retains all eleven foods",
    )
    check(len(compatibility_record["meals"]["snacks"]) == 3, "snack alias normalizes to snacks")
    first_breakfast = compatibility_record["meals"]["breakfast"][0]
    check(
        first_breakfast["quantity"] == 1 and first_breakfast["unit"] == "個",
        "quantity object normalizes to quantity and unit",
    )
    check(
        first_breakfast["nutrition"]["basis"] == "total",
        "direct item nutrition normalizes as consumed total",
    )
    check(
        compatibility_nutrition["totals"]
        == {"calories_kcal": 428.0, "protein_g": 16.5, "fat_g": 3.1, "carbs_g": 23.9},
        "direct calories and macro aliases are retained without multiplication",
    )
    check(compatibility_nutrition["unknown_calorie_count"] == 8, "unknown foods remain explicitly unknown")
    check(
        compatibility_record["meals"]["lunch"][0]["notes"] == "2枚を2人でシェア",
        "meal item notes are retained",
    )
    check(
        compatibility_record["notes"] == "1週間ぶりのジム再開\n彼女と江戸川橋のnove.でランチ",
        "daily notes array preserves order as text",
    )
    check(
        workout_counts(compatibility_record["workout"])["set_count"] == 20,
        "compatibility input retains all workout sets",
    )
    check(compatibility_fixture == compatibility_original, "compatibility input object is not mutated")

    unknown_document = normalize_import_document(
        {
            "schema_version": "1.0",
            "date": "2026-07-25",
            "meals": {"dinner": [{"name": "おばあちゃん特製カレー"}]},
        }
    )
    unknown = resolve_record_nutrition(unknown_document["records"][0], fallback_only)
    check(unknown["totals"]["calories_kcal"] is None, "fallback estimate remains null in import")
    check(unknown["unknown_calorie_count"] == 1, "unknown calorie count is retained")

    quantity_nutrition = normalize_import_document(
        {
            "schema_version": "1.0",
            "date": "2026-07-19",
            "meals": {
                "snacks": [
                    {
                        "name": "商品A",
                        "quantity": 2,
                        "unit": "個",
                        "nutrition": {"calories_kcal": 100, "basis": "per_item"},
                    },
                    {
                        "name": "商品B",
                        "quantity": 180,
                        "unit": "g",
                        "nutrition": {"calories_kcal": 250, "basis": "per_100g"},
                    },
                ]
            },
        }
    )["records"][0]
    quantity_totals = resolve_record_nutrition(quantity_nutrition, fallback_only)
    check(quantity_totals["totals"]["calories_kcal"] == 650, "compatible quantity basis is calculated once")

    preview = preview_import(document, {"2026-07-26"})
    check(preview["conflict_count"] == 1, "existing date conflict is visible before save")
    check(preview["exercise_count"] == 6 and preview["set_count"] == 20, "preview counts structured workout")

    projection = canonical_to_projection(record, nutrition)
    exported = export_projection(projection)
    round_trip = normalize_import_document(exported)["records"][0]
    check(round_trip["date"] == record["date"], "export/import preserves date")
    check(workout_counts(round_trip["workout"]) == counts, "export/import preserves workout meaning")
    check(import_fingerprint(record) == import_fingerprint(deepcopy(record)), "content fingerprint is stable")

    legacy = normalize_import_document(
        {
            "日付": "2026-07-24",
            "体重": 83.4,
            "歩数": 8000,
            "朝": "なし",
            "筋トレ内容": {
                "種別": "Legacy Day",
                "ベンチプレス": "90kg 5,5,5,5",
            },
        }
    )
    check(legacy["warnings"], "legacy JSON produces a conversion warning")
    check(workout_counts(legacy["records"][0]["workout"])["set_count"] == 4, "legacy workout becomes ordered sets")

    quantity = normalize_import_document(
        {
            "schema_version": "1.0",
            "date": "2026-07-23",
            "meals": {"lunch": [{"name": "サラダ", "quantity": "少量"}]},
        }
    )
    item = quantity["records"][0]["meals"]["lunch"][0]
    check(item["quantity"] is None and item["quantity_text"] == "少量", "free quantity text is not calculated")

    anomalous = normalize_import_document(
        {"schema_version": "1.0", "date": "2026-07-22", "weight": 400, "steps": 120000}
    )["records"][0]
    check(len(detect_anomalies(anomalous)) == 2, "anomalies warn without blocking")

    try:
        normalize_import_document(
            [
                {"schema_version": "1.0", "date": "2026-07-21"},
                {"schema_version": "1.0", "date": "2026-07-21"},
            ]
        )
    except ImportValidationError:
        print("PASS: duplicate dates in one import are rejected")
    else:
        raise AssertionError("duplicate dates must be rejected")

    try:
        normalize_import_document({"schema_version": "2.0", "date": "2026-07-20"})
    except ImportValidationError:
        print("PASS: unknown schema version is rejected")
    else:
        raise AssertionError("unknown schema version must be rejected")

    after = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    check(before == after, "records.csv is unchanged")
    print("PR13 import validation passed.")


if __name__ == "__main__":
    main()
