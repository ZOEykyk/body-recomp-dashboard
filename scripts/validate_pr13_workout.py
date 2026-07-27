from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyos_import import canonical_to_projection, normalize_import_document, resolve_record_nutrition, workout_counts  # noqa: E402
from workout_history import workout_history_rows  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/pr13_acceptance_2026-07-26.json").read_text(encoding="utf-8"))
    original = deepcopy(fixture)
    record = normalize_import_document(fixture)["records"][0]
    nutrition = resolve_record_nutrition(record, lambda _text, _meal: {"items": []})
    projection = canonical_to_projection(record, nutrition)
    projection["日付"] = pd.Timestamp(record["date"])

    counts = workout_counts(record["workout"])
    check(counts == {"session_count": 1, "exercise_count": 6, "set_count": 20}, "structured workout counts")
    history = workout_history_rows(pd.DataFrame([projection]))
    check(len(history) == 6, "history has one row per exercise")
    check(history[0]["プログラム"] == "Week3 Day2【Hypertrophy】", "program name is displayed")
    check(history[0]["時間"] == "75分", "duration is displayed")
    check(history[0]["種目"] == "インクラインDBプレス", "exercise name is displayed")
    check(history[0]["重量・回数"] == "32kg×10 / 32kg×10 / 32kg×9 / 32kg×8", "ordered sets are displayed")
    check(sum(row["セット数"] for row in history) == 20, "history retains every listed set")
    check(fixture == original, "workout transformation does not mutate input")
    print("PR13 workout validation passed.")


if __name__ == "__main__":
    main()
