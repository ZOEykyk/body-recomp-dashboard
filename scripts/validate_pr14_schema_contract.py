from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyos_import import (  # noqa: E402
    ImportValidationError,
    canonical_document_payload,
    normalize_import_document,
    workout_counts,
)
from schema_contract import load_daily_log_schema, validate_schema_record  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def fixture(name: str) -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))


def rejected(name: str) -> ImportValidationError:
    try:
        normalize_import_document(fixture(name))
    except ImportValidationError as exc:
        return exc
    raise AssertionError(f"{name} must be rejected")


def main() -> None:
    records_path = ROOT / "records.csv"
    records_before = hashlib.sha256(records_path.read_bytes()).hexdigest()
    schema_before = hashlib.sha256((ROOT / "schemas/bodyos-daily-log.schema.json").read_bytes()).hexdigest()

    canonical_input = fixture("schema_1_0_canonical_example.json")
    canonical_original = deepcopy(canonical_input)
    check(not validate_schema_record(canonical_input), "canonical example validates against the unchanged Schema 1.0")
    canonical_document = normalize_import_document(canonical_input)
    check(
        canonical_document["metadata"]["normalization"]["change_count"] == 0,
        "canonical example needs zero compatibility changes",
    )
    check(canonical_input == canonical_original, "canonical example normalization does not mutate input")

    safe_input = fixture("pr14_safe_compatibility.json")
    safe_original = deepcopy(safe_input)
    safe_document = normalize_import_document(safe_input)
    safe_record = safe_document["records"][0]
    changes = safe_document["metadata"]["normalization"]["changes"]
    change_pairs = {(item["source_path"], item["target_path"]) for item in changes}
    expected_pairs = {
        ("condition_score", "condition"),
        ("nutrition", "nutrition_totals"),
        ("sleep_hours", "sleep"),
        ("meals.breakfast[0].nutrition.calories", "meals.breakfast[0].nutrition.calories_kcal"),
        ("meals.breakfast[0].nutrition.protein", "meals.breakfast[0].nutrition.protein_g"),
        ("meals.breakfast[0].nutrition.fat", "meals.breakfast[0].nutrition.fat_g"),
        ("meals.breakfast[0].nutrition.carbs", "meals.breakfast[0].nutrition.carbs_g"),
        ("workout.sessions[0].exercises", "workout.exercises"),
        ("workout.exercises[0].sets[0].type", "workout.exercises[0].sets[0].set_type"),
    }
    check(expected_pairs <= change_pairs, "safe compatibility aliases produce the expected normalization report")
    check(safe_record["condition"] == 7 and safe_record["sleep"]["hours"] == 7, "safe top-level aliases normalize")
    breakfast_nutrition = safe_record["meals"]["breakfast"][0]["nutrition"]
    check(
        breakfast_nutrition
        == {"calories_kcal": 150.0, "protein_g": 20.0, "fat_g": 2.0, "carbs_g": 12.0, "basis": "total"},
        "food nutrition aliases normalize without changing values",
    )
    check(
        workout_counts(safe_record["workout"]) == {"session_count": 1, "exercise_count": 1, "set_count": 1}
        and safe_record["workout"]["exercises"][0]["sets"][0]["set_type"] == "work",
        "single session and workout set type normalize safely",
    )
    check(safe_input == safe_original, "safe compatibility normalization does not mutate input")

    conflict = rejected("pr14_conflicting_aliases.json")
    check(any(issue["code"] == "alias_conflict" and issue["path"] == "condition_score" for issue in conflict.issues), "conflicting condition aliases are rejected")

    invalid_basis = rejected("pr14_invalid_basis.json")
    check(
        any(
            issue["path"] == "meals.breakfast[0].nutrition.basis"
            and issue["code"] == "invalid_enum"
            and "per_item" in str(issue.get("suggestion"))
            for issue in invalid_basis.issues
        ),
        "estimated_total is rejected with path and allowed basis values",
    )

    invalid_aliases = rejected("pr14_invalid_aliases.json")
    invalid_paths = {issue["path"] for issue in invalid_aliases.issues}
    check({"summary", "memo", "nutrition_summary"} <= invalid_paths, "unknown top-level properties are all reported")
    check("workout.sessions" in invalid_paths, "multiple workout sessions are not flattened")
    check(len(invalid_aliases.issues) >= 5, "multiple independent Schema errors are collected in one pass")
    check(all(issue.get("path") for issue in invalid_aliases.issues), "every validation error has a JSON Path")

    canonical_payload = canonical_document_payload(canonical_document)
    check(not validate_schema_record(canonical_payload), "canonical Preview payload validates directly")
    round_trip = normalize_import_document(canonical_payload)
    check(round_trip["metadata"]["normalization"]["change_count"] == 0, "round trip requires zero normalization changes")
    round_trip_payload = canonical_document_payload(round_trip)
    check(canonical_payload == round_trip_payload, "round trip preserves the complete canonical data contract")
    for field in ("weight", "sleep", "condition", "steps", "meals", "workout", "notes", "nutrition_totals"):
        check(canonical_payload[field] == round_trip_payload[field], f"round trip preserves {field}")

    pr13_fixture = fixture("pr13_compatibility_input_2026-07-26.json")
    pr13_document = normalize_import_document(pr13_fixture)
    pr13_record = pr13_document["records"][0]
    check(sum(len(items) for items in pr13_record["meals"].values()) == 11, "PR13 fixture still retains eleven foods")
    check(len(pr13_record["meals"]["snacks"]) == 3, "PR13 singular snack compatibility remains intact")
    check(workout_counts(pr13_record["workout"])["set_count"] == 20, "PR13 structured workout remains intact")

    same_alias = normalize_import_document(
        {"schema_version": "1.0", "date": "2026-08-07", "condition": 8, "condition_score": 8}
    )
    check(
        same_alias["records"][0]["condition"] == 8
        and same_alias["metadata"]["normalization"]["change_count"] == 1,
        "matching canonical and alias values keep canonical and report alias removal",
    )

    check(load_daily_log_schema()["properties"]["schema_version"]["const"] == "1.0", "Schema remains version 1.0")
    schema_after = hashlib.sha256((ROOT / "schemas/bodyos-daily-log.schema.json").read_bytes()).hexdigest()
    check(schema_before == schema_after, "validation does not rewrite the Schema file")
    records_after = hashlib.sha256(records_path.read_bytes()).hexdigest()
    check(records_before == records_after, "validation does not modify records.csv")
    main_records = subprocess.run(
        ["git", "show", "main:records.csv"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    check(records_path.read_bytes() == main_records, "records.csv is identical to main")
    schema_diff = subprocess.run(
        ["git", "diff", "--exit-code", "main", "--", "schemas/bodyos-daily-log.schema.json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    check(schema_diff.returncode == 0, "PR14 does not change the canonical Schema file")
    print("PR14 Schema Contract Hardening validation passed.")


if __name__ == "__main__":
    main()
