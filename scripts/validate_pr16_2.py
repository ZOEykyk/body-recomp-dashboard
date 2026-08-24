from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import time

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    records = ROOT / "records.csv"
    schema = ROOT / "schemas" / "bodyos-daily-log.schema.json"
    records_before = hashlib.sha256(records.read_bytes()).hexdigest()
    schema_before = hashlib.sha256(schema.read_bytes()).hexdigest()

    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_label_ocr_runtime.py"],
        cwd=ROOT,
        check=True,
    )
    started = time.perf_counter()
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    startup_ms = (time.perf_counter() - started) * 1000
    check(not app.exception, "Streamlit app renders without OCR initialization errors")
    check(
        any(item.proto.label == "栄養ラベル画像" for item in app.get("file_uploader")),
        "Label image uploader renders",
    )
    check(any(item.key == "smart-food-query" for item in app.text_input), "normal Food Search remains available")
    check(startup_ms < 15_000, "normal app startup remains bounded")

    check(hashlib.sha256(records.read_bytes()).hexdigest() == records_before, "records.csv unchanged")
    check(hashlib.sha256(schema.read_bytes()).hexdigest() == schema_before, "Canonical Schema unchanged")
    migration_diff = subprocess.run(
        ["git", "diff", "--exit-code", "origin/main...HEAD", "--", "supabase/migrations"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    check(migration_diff.returncode == 0, "Supabase migrations unchanged")
    print(f"PERFORMANCE: normal_startup_ms={startup_ms:.1f}")
    print("PR16.2 Label OCR Runtime validation passed.")


if __name__ == "__main__":
    main()
