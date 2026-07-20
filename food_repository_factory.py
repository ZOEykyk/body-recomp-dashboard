from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any, Callable

from food_master_repository import FoodMasterRepository, JsonFoodMasterRepository
from supabase_food_master_repository import (
    DEFAULT_TIMEOUT_SECONDS,
    SupabaseFoodMasterRepository,
    SupabaseRepositoryError,
    SupabaseRestClient,
)


LOGGER = logging.getLogger(__name__)
REPOSITORY_MODES = {"json_only", "fallback_json", "strict_supabase"}


class UnavailableFoodMasterRepository(FoodMasterRepository):
    """Read-safe strict-mode repository used when Supabase is unavailable."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason
        self._last_error = reason

    def list_foods(self, user_id: str) -> list[dict[str, Any]]:
        return []

    def get_food(self, user_id: str, food_id: str) -> dict[str, Any] | None:
        return None

    def _write_error(self) -> None:
        raise SupabaseRepositoryError("Supabase Food Knowledge storage is unavailable")

    def upsert_food(self, user_id: str, food: dict[str, Any]) -> dict[str, Any]:
        self._write_error()
        return {}

    def archive_food(self, user_id: str, food_id: str) -> None:
        self._write_error()

    def append_encounter(self, user_id: str, encounter: dict[str, Any]) -> dict[str, Any]:
        self._write_error()
        return {}

    def get_encounter_by_idempotency(self, user_id: str, idempotency_key: str) -> dict[str, Any] | None:
        return None

    def list_candidates(self, user_id: str) -> list[dict[str, Any]]:
        return []

    def list_encounters(self, user_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        return []

    def save_encounter_idempotently(
        self,
        user_id: str,
        food: dict[str, Any],
        encounter: dict[str, Any],
    ) -> dict[str, Any]:
        self._write_error()
        return {}

    def get_repository_status(self) -> dict[str, Any]:
        return {
            "storage": "Supabase",
            "connection": "Error",
            "repository": type(self).__name__,
            "last_successful_read": None,
            "last_successful_write": None,
            "migration_status": "unknown",
            "unsynced_count": 0,
            "warning": "Supabaseへ接続できません。Food Knowledgeの書き込みは停止中です。",
        }


class FallbackFoodMasterRepository(FoodMasterRepository):
    """Sticky session fallback that prevents repeated writes across two stores."""

    def __init__(
        self,
        primary: FoodMasterRepository | None,
        fallback: JsonFoodMasterRepository,
        *,
        initial_error: str | None = None,
    ) -> None:
        super().__init__()
        self.primary = primary
        self.fallback = fallback
        self._using_fallback = primary is None
        self._fallback_reason = initial_error
        self._unsynced_count = 0

    def _call(self, method: str, *args: Any, write: bool = False, **kwargs: Any) -> Any:
        if not self._using_fallback and self.primary is not None:
            try:
                return getattr(self.primary, method)(*args, **kwargs)
            except Exception as exc:
                self._using_fallback = True
                self._fallback_reason = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("Food Knowledge switched to JSON fallback: %s", type(exc).__name__)
        result = getattr(self.fallback, method)(*args, **kwargs)
        if write:
            inserted = not isinstance(result, dict) or bool(result.get("inserted", True))
            self._unsynced_count += int(inserted)
        return result

    def list_foods(self, user_id: str) -> list[dict[str, Any]]:
        return self._call("list_foods", user_id)

    def get_food(self, user_id: str, food_id: str) -> dict[str, Any] | None:
        return self._call("get_food", user_id, food_id)

    def upsert_food(self, user_id: str, food: dict[str, Any]) -> dict[str, Any]:
        return self._call("upsert_food", user_id, food, write=True)

    def archive_food(self, user_id: str, food_id: str) -> None:
        self._call("archive_food", user_id, food_id, write=True)

    def append_encounter(self, user_id: str, encounter: dict[str, Any]) -> dict[str, Any]:
        return self._call("append_encounter", user_id, encounter, write=True)

    def get_encounter_by_idempotency(self, user_id: str, idempotency_key: str) -> dict[str, Any] | None:
        return self._call("get_encounter_by_idempotency", user_id, idempotency_key)

    def list_candidates(self, user_id: str) -> list[dict[str, Any]]:
        return self._call("list_candidates", user_id)

    def list_encounters(self, user_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self._call("list_encounters", user_id, limit=limit)

    def save_encounter_idempotently(
        self,
        user_id: str,
        food: dict[str, Any],
        encounter: dict[str, Any],
    ) -> dict[str, Any]:
        return self._call("save_encounter_idempotently", user_id, food, encounter, write=True)

    def get_repository_status(self) -> dict[str, Any]:
        active = self.fallback if self._using_fallback or self.primary is None else self.primary
        status = deepcopy(active.get_repository_status())
        status.update(
            {
                "connection": "Fallback" if self._using_fallback else "Connected",
                "repository": type(active).__name__,
                "unsynced_count": self._unsynced_count,
                "warning": (
                    "Supabase障害のためLocal JSONへ保存中です。復旧後に未同期データの移行が必要です。"
                    if self._using_fallback
                    else status.get("warning")
                ),
            }
        )
        return status


def normalize_repository_mode(config: dict[str, str]) -> str:
    repository = str(config.get("FOOD_KNOWLEDGE_REPOSITORY") or "json").strip().lower()
    explicit_mode = str(config.get("FOOD_KNOWLEDGE_MODE") or "").strip().lower()
    if explicit_mode in REPOSITORY_MODES:
        return explicit_mode
    if repository in {"json", "json_only", "local"}:
        return "json_only"
    if repository == "strict_supabase":
        return "strict_supabase"
    return "fallback_json"


def create_food_master_repository(
    config: dict[str, str],
    json_repository: JsonFoodMasterRepository,
    *,
    transport: Callable[..., Any] | None = None,
) -> FoodMasterRepository:
    mode = normalize_repository_mode(config)
    if mode == "json_only":
        return json_repository

    url = str(config.get("SUPABASE_URL") or "").strip()
    api_key = str(config.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("SUPABASE_ANON_KEY") or "").strip()
    if not url or not api_key:
        reason = "Supabase secrets are not configured"
        LOGGER.warning("Food Knowledge Supabase repository unavailable: missing configuration")
        if mode == "fallback_json":
            return FallbackFoodMasterRepository(None, json_repository, initial_error=reason)
        return UnavailableFoodMasterRepository(reason)

    try:
        timeout = float(config.get("SUPABASE_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    repository = SupabaseFoodMasterRepository(
        SupabaseRestClient(url, api_key, timeout=timeout, transport=transport)
    )
    try:
        repository.health_check()
    except Exception as exc:
        LOGGER.warning("Food Knowledge Supabase health check failed: %s", type(exc).__name__)
        if mode == "fallback_json":
            return FallbackFoodMasterRepository(None, json_repository, initial_error=f"{type(exc).__name__}: {exc}")
        return UnavailableFoodMasterRepository(f"{type(exc).__name__}: {exc}")
    if mode == "fallback_json":
        return FallbackFoodMasterRepository(repository, json_repository)
    return repository


__all__ = [
    "FallbackFoodMasterRepository",
    "REPOSITORY_MODES",
    "UnavailableFoodMasterRepository",
    "create_food_master_repository",
    "normalize_repository_mode",
]
