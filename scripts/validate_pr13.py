from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyos_import import normalize_import_document, preview_import, workout_counts  # noqa: E402
from dashboard_aggregation import aggregate_record  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    csv_path = ROOT / "records.csv"
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    fixture = json.loads((ROOT / "tests/fixtures/pr13_acceptance_2026-07-26.json").read_text(encoding="utf-8"))
    document = normalize_import_document(fixture)

    captured = io.StringIO()
    with redirect_stdout(captured), redirect_stderr(captured):
        app = importlib.import_module("app")

    projected, diagnostics = app.build_import_rows(document)
    empty = pd.DataFrame(columns=app.COLUMNS)
    first, first_counts = app.apply_import_rows(empty, projected, diagnostics, "update")
    check(len(first) == 1 and first_counts["added"] == 1, "first import adds one daily record")
    second, second_counts = app.apply_import_rows(first, projected, diagnostics, "update")
    check(len(second) == 1 and second_counts["updated"] == 1, "identical re-import updates without duplicate")
    check(int(second.iloc[0]["筋トレセッション数"]) == 1, "re-import keeps one workout session")
    check(int(second.iloc[0]["筋トレ種目数"]) == 6, "re-import keeps six exercises")
    check(int(second.iloc[0]["筋トレセット数"]) == 20, "re-import does not duplicate workout sets")

    aggregate = aggregate_record(second.iloc[0])
    check(aggregate["weight_kg"] == 83.2, "dashboard weight matches import")
    check(aggregate["sleep_hours"] == 8, "dashboard sleep matches import")
    check(aggregate["condition"] == 8, "dashboard condition matches import")
    check(aggregate["steps"] == 11786, "dashboard steps match import")
    check(aggregate["calories_kcal"] == 2200, "dashboard calories match one nutrition path")
    check(aggregate["workout_duration_minutes"] == 75, "dashboard workout duration matches import")

    changed_fixture = json.loads(json.dumps(fixture, ensure_ascii=False))
    changed_fixture["steps"] = 12001
    changed = normalize_import_document(changed_fixture)
    changed_projected, changed_diagnostics = app.build_import_rows(changed)
    changed_result, changed_counts = app.apply_import_rows(second, changed_projected, changed_diagnostics, "update")
    check(len(changed_result) == 1 and changed_counts["updated"] == 1, "changed same-day content updates one row")
    check(int(changed_result.iloc[0]["歩数"]) == 12001, "changed content is reflected")
    check(
        changed_result.iloc[0]["Import ID"] != second.iloc[0]["Import ID"],
        "changed content has a different stable import identity",
    )

    cancelled, cancel_counts = app.apply_import_rows(second, changed_projected, changed_diagnostics, "cancel")
    check(cancel_counts["skipped"] == 1 and int(cancelled.iloc[0]["歩数"]) == 11786, "cancel preserves stored day")
    replaced, replace_counts = app.apply_import_rows(second, changed_projected, changed_diagnostics, "replace")
    check(replace_counts["replaced"] == 1 and int(replaced.iloc[0]["歩数"]) == 12001, "replace swaps the daily projection")

    preview = preview_import(document, {"2026-07-26"})
    counts = workout_counts(document["records"][0]["workout"])
    check(preview["conflict_count"] == 1, "preview reports same-day conflict")
    check(preview["meal_item_count"] == 4, "preview reports all meal items")
    check(counts["exercise_count"] == 6, "acceptance exercise count")
    check(counts["set_count"] == 20, "listed acceptance reps produce twenty sets")

    after = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    check(before == after, "validation does not modify records.csv")
    print("PR13 integrated validation passed.")


if __name__ == "__main__":
    main()
