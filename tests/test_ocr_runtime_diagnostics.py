from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from label_ocr_runtime import OcrRuntimeCache
import ocr_runtime_diagnostics as diagnostics


class OcrRuntimeDiagnosticsTests(unittest.TestCase):
    def tearDown(self) -> None:
        diagnostics._environment_metadata.cache_clear()

    def test_environment_probe_reports_only_runtime_metadata(self) -> None:
        commands = {
            "--version": ("tesseract 5.5.2\nprivate build details", None),
            "--list-langs": ("List of available languages in /private/path (2):\neng\njpn", None),
        }
        with patch.object(
            diagnostics.shutil, "which", return_value="/private/bin/tesseract"
        ), patch.object(
                diagnostics,
                "_run_metadata_command",
                side_effect=lambda executable, argument: commands[argument],
        ), patch.object(
                diagnostics,
                "_package_version",
                side_effect=lambda name: {
                    "Pillow": "11.0",
                    "pytesseract": "0.3.13",
                    "streamlit": "1.59.0",
                }[name],
        ), patch.object(
                diagnostics,
                "ocr_runtime_state",
                return_value={"initialized": False, "status": "not_initialized"},
        ):
            result = diagnostics.ocr_runtime_metadata_diagnostics(OcrRuntimeCache())

        self.assertTrue(result["tesseract_executable_detected"])
        self.assertEqual(result["tesseract_version"], "5.5.2")
        self.assertEqual(result["available_languages"], ["eng", "jpn"])
        self.assertTrue(result["jpn_available"])
        self.assertTrue(result["eng_available"])
        self.assertEqual(result["pillow_version"], "11.0")
        self.assertEqual(result["pytesseract_version"], "0.3.13")
        self.assertEqual(result["streamlit_version"], "1.59.0")
        self.assertRegex(result["python_version"], r"^\d+\.\d+\.\d+$")
        self.assertFalse(result["runtime"]["initialized"])
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("/private", serialized)
        self.assertNotIn("SECRET", serialized)

    def test_cache_diagnostics_never_expose_keys_or_ocr_payload(self) -> None:
        cache = OcrRuntimeCache(max_entries=3)
        cache.get_or_compute(
            "private-image-sha-and-engine-key",
            lambda: {"raw_text": "SECRET RAW OCR TEXT"},
        )
        metadata = cache.metadata()
        self.assertEqual(metadata, {"status": "populated", "entry_count": 1, "max_entries": 3})
        serialized = json.dumps(metadata, sort_keys=True)
        self.assertNotIn("private-image", serialized)
        self.assertNotIn("SECRET", serialized)

    def test_missing_runtime_is_reported_without_exception(self) -> None:
        with patch.object(diagnostics.shutil, "which", return_value=None), patch.object(
            diagnostics, "_package_version", return_value=None
        ):
            result = diagnostics.ocr_runtime_metadata_diagnostics(OcrRuntimeCache())
        self.assertFalse(result["tesseract_executable_detected"])
        self.assertEqual(result["probe_status"], "unavailable")
        self.assertEqual(result["available_languages"], [])
        self.assertFalse(result["jpn_available"])
        self.assertFalse(result["eng_available"])


if __name__ == "__main__":
    unittest.main()
