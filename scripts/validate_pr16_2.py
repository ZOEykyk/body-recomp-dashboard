from __future__ import annotations

import hashlib
import json
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
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*ocr_runtime*.py"],
        cwd=ROOT,
        check=True,
    )
    started = time.perf_counter()
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    startup_ms = (time.perf_counter() - started) * 1000
    check(not app.exception, "Streamlit app renders without OCR initialization errors")
    check(
        any(item.proto.label == "栄養ラベルを撮影" for item in app.get("camera_input")),
        "Label camera input renders",
    )
    check(
        any("栄養成分表示へ近づき" in str(item.value) for item in app.info),
        "mobile camera guidance renders",
    )
    input_method = next(item for item in app.radio if item.key == "label-ocr-input-method")
    app = input_method.set_value("画像をUpload").run()
    check(not app.exception, "switching label input method renders without exceptions")
    check(
        any(item.proto.label == "栄養ラベル画像" for item in app.get("file_uploader")),
        "Label image uploader renders",
    )
    check(any(item.key == "smart-food-query" for item in app.text_input), "normal Food Search remains available")
    check(startup_ms < 15_000, "normal app startup remains bounded")

    diagnostics_toggle = next(item for item in app.toggle if item.label == "Food Knowledge詳細を表示")
    app = diagnostics_toggle.set_value(True).run()
    check(not app.exception, "metadata-only diagnostics render without exceptions")
    json_values = [json.loads(item.value) for item in app.get("json")]
    debug_payload = next(item for item in json_values if isinstance(item, dict) and "ocr_runtime" in item)
    ocr_runtime = debug_payload["ocr_runtime"]
    check("tesseract_executable_detected" in ocr_runtime, "Tesseract detection is observable")
    check("available_languages" in ocr_runtime, "OCR languages are observable")
    check("runtime" in ocr_runtime and "cache" in ocr_runtime, "OCR initialization and cache metadata are observable")
    serialized_diagnostics = json.dumps(debug_payload, ensure_ascii=False, sort_keys=True)
    for forbidden in ("raw_text", "image_sha256", "SECRET", "SUPABASE_KEY"):
        check(forbidden not in serialized_diagnostics, f"diagnostics omit {forbidden}")

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
