from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as package_version
import shutil
import subprocess
import sys
from typing import Any

from label_ocr_runtime import OCR_RUNTIME_CACHE, OcrRuntimeCache, ocr_runtime_state


OCR_RUNTIME_DIAGNOSTICS_VERSION = "pr16.2-cloud-v2"


def _package_version(name: str) -> str | None:
    try:
        return package_version(name)
    except (PackageNotFoundError, ValueError):
        return None


def _run_metadata_command(executable: str, argument: str) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            [executable, argument],
            capture_output=True,
            check=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, type(exc).__name__
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return output, None


@lru_cache(maxsize=1)
def _environment_metadata() -> dict[str, Any]:
    executable = shutil.which("tesseract")
    version_output = None
    languages_output = None
    errors: list[str] = []
    if executable:
        version_output, version_error = _run_metadata_command(executable, "--version")
        languages_output, languages_error = _run_metadata_command(executable, "--list-langs")
        errors.extend(error for error in (version_error, languages_error) if error)

    tesseract_version = None
    if version_output:
        first_line = version_output.splitlines()[0].strip()
        tesseract_version = first_line.removeprefix("tesseract ").strip() or None

    available_languages: list[str] = []
    for line in (languages_output or "").splitlines():
        value = line.strip()
        if value and not value.lower().startswith("list of available languages"):
            available_languages.append(value)
    available_languages = sorted(set(available_languages))

    return {
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "streamlit_version": _package_version("streamlit"),
        "tesseract_executable_detected": bool(executable),
        "tesseract_version": tesseract_version,
        "available_languages": available_languages,
        "jpn_available": "jpn" in available_languages,
        "eng_available": "eng" in available_languages,
        "pillow_version": _package_version("Pillow"),
        "pytesseract_version": _package_version("pytesseract"),
        "probe_status": "ready" if executable and not errors else "unavailable",
        "probe_error_types": sorted(set(errors)),
    }


def ocr_runtime_metadata_diagnostics(
    cache: OcrRuntimeCache | None = None,
) -> dict[str, Any]:
    """Return runtime metadata without image, OCR text, cache keys, or environment values."""
    return {
        "diagnostics_version": OCR_RUNTIME_DIAGNOSTICS_VERSION,
        **deepcopy(_environment_metadata()),
        "runtime": ocr_runtime_state(),
        "cache": (cache or OCR_RUNTIME_CACHE).metadata(),
    }


__all__ = [
    "OCR_RUNTIME_DIAGNOSTICS_VERSION",
    "ocr_runtime_metadata_diagnostics",
]
