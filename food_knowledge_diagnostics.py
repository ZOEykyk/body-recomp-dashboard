from __future__ import annotations

import hashlib
from functools import lru_cache
import os
import subprocess
from typing import Any

from food_source_policy import select_nutrition_source


FOOD_KNOWLEDGE_DIAGNOSTICS_VERSION = "pr15.1-cloud-v2"


@lru_cache(maxsize=1)
def runtime_source_revision() -> str:
    """Return the deployed source revision without exposing environment values."""
    for name in ("STREAMLIT_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"):
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value[:12]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return result.stdout.strip() or "unavailable"


def food_knowledge_user_key(user_id: str) -> str:
    """Return a non-reversible identifier suitable for production diagnostics."""
    return hashlib.sha256(str(user_id or "").encode("utf-8")).hexdigest()[:12]


def _repository_status(repository: Any) -> dict[str, Any]:
    try:
        raw = repository.get_repository_status()
    except Exception as exc:
        return {
            "storage": "Unknown",
            "connection": "Error",
            "repository": type(repository).__name__,
            "migration_status": "unknown",
            "unsynced_count": None,
            "status_error_type": type(exc).__name__,
        }
    return {
        "storage": str(raw.get("storage") or "Unknown"),
        "connection": str(raw.get("connection") or "Unknown"),
        "repository": str(raw.get("repository") or type(repository).__name__),
        "migration_status": str(raw.get("migration_status") or "unknown"),
        "unsynced_count": raw.get("unsynced_count"),
        "status_error_type": None,
    }


def _source_types(food: dict[str, Any] | None) -> list[str]:
    source_types: set[str] = set()
    for candidate in (food or {}).get("nutrition_sources") or []:
        if not isinstance(candidate, dict):
            continue
        source = candidate.get("source")
        source_types.add(
            str(source.get("source_type") or "unknown") if isinstance(source, dict) else "unknown"
        )
    return sorted(source_types)


def _selection_diagnostics(food: dict[str, Any] | None) -> dict[str, Any]:
    sources = (food or {}).get("nutrition_sources") or []
    selection = select_nutrition_source(sources)
    selected = selection.get("selected") or {}
    source = selected.get("source") if isinstance(selected, dict) else None
    return {
        "nutrition_source_count": len(sources),
        "source_types": _source_types(food),
        "source_selection_status": str(selection.get("status") or "unknown"),
        "source_selected": bool(selected),
        "selected_source_type": (
            str(source.get("source_type") or "unknown")
            if isinstance(source, dict) and selected
            else None
        ),
    }


def repository_runtime_diagnostics(
    repository: Any,
    user_id: str,
    knowledge: dict[str, Any],
    *,
    cached_personal_food_count: int | None = None,
) -> dict[str, Any]:
    """Describe the active read path without exposing credentials or food values."""
    personal_foods = (knowledge or {}).get("personal_foods") or []
    status = _repository_status(repository)
    return {
        "diagnostics_version": FOOD_KNOWLEDGE_DIAGNOSTICS_VERSION,
        "source_revision": runtime_source_revision(),
        "repository_type": type(repository).__name__,
        "repository_status": status,
        "fallback_active": status["connection"] == "Fallback",
        "cache_revision": repository.cache_revision(),
        "cached_personal_food_count": (
            len(personal_foods)
            if cached_personal_food_count is None
            else int(cached_personal_food_count)
        ),
        "knowledge_personal_food_count": len(personal_foods),
        "user_key": food_knowledge_user_key(user_id),
    }


def confirmed_save_diagnostics(
    repository: Any,
    user_id: str,
    stored: dict[str, Any],
    *,
    revision_before: int,
) -> dict[str, Any]:
    """Read back a confirmed food and report metadata-only persistence evidence."""
    food_id = str((stored or {}).get("food_id") or "")
    result: dict[str, Any] = {
        "food_id": food_id,
        "save_user_key": food_knowledge_user_key(user_id),
        "repository_type": type(repository).__name__,
        "repository_status": _repository_status(repository),
        "cache_revision_before": revision_before,
        "cache_revision_after": repository.cache_revision(),
        "stored_status": str((stored or {}).get("status") or "missing"),
        "stored_selection": _selection_diagnostics(stored),
        "post_save_snapshot_count": None,
        "post_save_snapshot_contains_food": False,
        "snapshot_status": None,
        "snapshot_selection": None,
        "snapshot_error_type": None,
    }
    try:
        snapshot = repository.build_snapshot(user_id)
        foods = snapshot.get("personal_foods") or []
        matched = next((food for food in foods if str(food.get("food_id") or "") == food_id), None)
        result.update(
            {
                "post_save_snapshot_count": len(foods),
                "post_save_snapshot_contains_food": matched is not None,
                "snapshot_status": str((matched or {}).get("status") or "missing"),
                "snapshot_selection": _selection_diagnostics(matched),
                "cache_revision_after_snapshot": repository.cache_revision(),
                "repository_status": _repository_status(repository),
            }
        )
    except Exception as exc:
        result["snapshot_error_type"] = type(exc).__name__
    return result


__all__ = [
    "FOOD_KNOWLEDGE_DIAGNOSTICS_VERSION",
    "confirmed_save_diagnostics",
    "food_knowledge_user_key",
    "repository_runtime_diagnostics",
    "runtime_source_revision",
]
