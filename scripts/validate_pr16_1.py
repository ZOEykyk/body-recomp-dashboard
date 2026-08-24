from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    records_path = ROOT / "records.csv"
    schema_path = ROOT / "schemas" / "bodyos-daily-log.schema.json"
    records_before = hashlib.sha256(records_path.read_bytes()).hexdigest()
    schema_before = hashlib.sha256(schema_path.read_bytes()).hexdigest()

    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_capture_foundation.py"],
        cwd=ROOT,
        check=True,
    )
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    check(not app.exception, "Streamlit app renders without exceptions")
    app.text_input(key="smart-food-query").input("ファミチキ").run()
    check(not app.exception, "Smart Food search rerun renders without exceptions")
    widget_keys = {
        element.key
        for collection in (app.text_input, app.selectbox, app.radio)
        for element in collection
        if element.key
    }
    for suffix in ("-name", "-meal", "-unit", "-basis", "-source"):
        check(
            any(str(key).startswith("new-food_candidate_") and str(key).endswith(suffix) for key in widget_keys),
            f"shared FoodCandidate Editor renders {suffix} widget",
        )
    check(hashlib.sha256(records_path.read_bytes()).hexdigest() == records_before, "records.csv unchanged")
    check(hashlib.sha256(schema_path.read_bytes()).hexdigest() == schema_before, "Canonical Schema unchanged")
    migration_diff = subprocess.run(
        ["git", "diff", "--exit-code", "origin/main...HEAD", "--", "supabase/migrations"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    check(migration_diff.returncode == 0, "Supabase migrations unchanged")
    print("PR16.1 Capture Foundation validation passed.")


if __name__ == "__main__":
    main()
