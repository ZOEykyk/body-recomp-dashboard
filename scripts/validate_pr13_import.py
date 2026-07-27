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
