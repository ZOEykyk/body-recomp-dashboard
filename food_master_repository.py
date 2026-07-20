from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from typing import Any

from food_master_models import normalized_identity_key
from food_master_models import FOOD_MASTER_VERSION, utc_now


class FoodMasterRepository(ABC):
    """Persistence boundary for personal food knowledge.

    Implementations own storage and serialization. Resolver consumers only receive
    copied snapshots, so a future Supabase adapter can replace the JSON adapter.
    """

    def __init__(self) -> None:
        self._last_successful_read: str | None = None
        self._last_successful_write: str | None = None
        self._last_error: str | None = None

    def _mark_read(self) -> None:
        self._last_successful_read = utc_now()
        self._last_error = None

    def _mark_write(self) -> None:
        self._last_successful_write = utc_now()
        self._last_error = None

    def _mark_error(self, exc: Exception) -> None:
        self._last_error = f"{type(exc).__name__}: {exc}"

    @abstractmethod
    def list_foods(self, user_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_food(self, user_id: str, food_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def upsert_food(self, user_id: str, food: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def archive_food(self, user_id: str, food_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def append_encounter(self, user_id: str, encounter: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_encounter_by_idempotency(self, user_id: str, idempotency_key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def list_candidates(self, user_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_encounters(self, user_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_knowledge_snapshot(
        self,
        user_id: str,
        *,
        include_encounters: bool = False,
    ) -> dict[str, Any]:
        """Return repository-owned knowledge without leaking mutable storage values."""
        return {
            "repository_type": type(self).__name__,
            "user_id": user_id,
            "personal_foods": self.list_foods(user_id),
            "encounters": self.list_encounters(user_id) if include_encounters else [],
        }

    def get_food_by_id(self, user_id: str, food_id: str) -> dict[str, Any] | None:
        return self.get_food(user_id, food_id)

    def find_food_candidates(self, user_id: str, identity: dict[str, Any]) -> list[dict[str, Any]]:
        key = normalized_identity_key(identity)
        return [food for food in self.list_foods(user_id) if normalized_identity_key(food) == key]

    def find_by_alias(self, user_id: str, normalized_alias: str) -> list[dict[str, Any]]:
        expected = " ".join(str(normalized_alias or "").lower().split())
        return [
            food
            for food in self.list_foods(user_id)
            if expected
            and expected in {" ".join(str(alias).lower().split()) for alias in food.get("aliases") or []}
        ]

    def list_active_foods(self, user_id: str) -> list[dict[str, Any]]:
        return [food for food in self.list_foods(user_id) if food.get("status") == "active"]

    def list_recent_foods(self, user_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        foods = sorted(self.list_foods(user_id), key=lambda food: str(food.get("updated_at") or ""), reverse=True)
        return foods[: max(int(limit), 0)]

    def list_top_used_foods(self, user_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        foods = sorted(
            self.list_foods(user_id),
            key=lambda food: (int(food.get("usage_count", food.get("use_count", 0)) or 0), str(food.get("last_used_at") or "")),
            reverse=True,
        )
        return foods[: max(int(limit), 0)]

    def create_or_update_food(self, user_id: str, food: dict[str, Any]) -> dict[str, Any]:
        return self.upsert_food(user_id, food)

    def save_encounter_idempotently(
        self,
        user_id: str,
        food: dict[str, Any],
        encounter: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a food usage and encounter once.

        Database adapters should override this with a transaction or RPC. The
        fallback preserves the PR11 interface for third-party adapters.
        """
        key = str(encounter.get("idempotency_key") or "")
        existing = self.get_encounter_by_idempotency(user_id, key)
        if existing is not None:
            return {
                "inserted": False,
                "duplicate": True,
                "food": self.get_food(user_id, str(existing.get("resolved_food_id") or "")),
                "encounter": existing,
            }
        stored_food = self.upsert_food(user_id, food)
        stored_encounter = self.append_encounter(user_id, encounter)
        return {"inserted": True, "duplicate": False, "food": stored_food, "encounter": stored_encounter}

    def build_snapshot(self, user_id: str, *, include_encounters: bool = False) -> dict[str, Any]:
        return self.get_knowledge_snapshot(user_id, include_encounters=include_encounters)

    def get_repository_status(self) -> dict[str, Any]:
        return {
            "storage": "Unknown",
            "connection": "Connected" if not self._last_error else "Error",
            "repository": type(self).__name__,
            "last_successful_read": self._last_successful_read,
            "last_successful_write": self._last_successful_write,
            "migration_status": "not_required",
            "unsynced_count": 0,
            "warning": None,
        }


class JsonFoodMasterRepository(FoodMasterRepository):
    """Local adapter; future database repositories can implement the same interface."""

    def __init__(self, master_path: Path, encounters_path: Path) -> None:
        super().__init__()
        self.master_path = Path(master_path)
        self.encounters_path = Path(encounters_path)
        self._transaction_lock = RLock()

    def _read_master(self) -> dict[str, Any]:
        if not self.master_path.exists():
            return {"schema_version": FOOD_MASTER_VERSION, "foods": []}
        try:
            payload = json.loads(self.master_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": FOOD_MASTER_VERSION, "foods": []}
        foods = payload.get("foods", []) if isinstance(payload, dict) else []
        return {"schema_version": FOOD_MASTER_VERSION, "foods": [food for food in foods if isinstance(food, dict)]}

    def _write_master(self, payload: dict[str, Any]) -> None:
        self.master_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.master_path.with_suffix(f"{self.master_path.suffix}.tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(self.master_path)

    def list_foods(self, user_id: str) -> list[dict[str, Any]]:
        foods = [
            deepcopy(food)
            for food in self._read_master()["foods"]
            if food.get("owner_user_id", food.get("user_id")) == user_id
        ]
        self._mark_read()
        return foods

    def get_food(self, user_id: str, food_id: str) -> dict[str, Any] | None:
        for food in self.list_foods(user_id):
            if food.get("food_id") == food_id:
                return food
        return None

    def upsert_food(self, user_id: str, food: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy(food)
        stored["user_id"] = user_id
        stored["owner_user_id"] = user_id
        stored["updated_at"] = stored.get("updated_at") or utc_now()
        if not stored.get("food_id"):
            raise ValueError("food_id is required")
        payload = self._read_master()
        foods = payload["foods"]
        for index, existing in enumerate(foods):
            if existing.get("owner_user_id", existing.get("user_id")) == user_id and existing.get("food_id") == stored["food_id"]:
                foods[index] = stored
                break
        else:
            foods.append(stored)
        self._write_master(payload)
        self._mark_write()
        return deepcopy(stored)

    def archive_food(self, user_id: str, food_id: str) -> None:
        food = self.get_food(user_id, food_id)
        if food is None:
            return
        food["status"] = "archived"
        food["updated_at"] = utc_now()
        self.upsert_food(user_id, food)

    def append_encounter(self, user_id: str, encounter: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy(encounter)
        stored["user_id"] = user_id
        stored["owner_user_id"] = user_id
        existing = self.get_encounter_by_idempotency(user_id, str(stored.get("idempotency_key") or ""))
        if existing is not None:
            return existing
        self.encounters_path.parent.mkdir(parents=True, exist_ok=True)
        with self.encounters_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(stored, ensure_ascii=False) + "\n")
        self._mark_write()
        return stored

    def get_encounter_by_idempotency(self, user_id: str, idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key or not self.encounters_path.exists():
            return None
        try:
            lines = self.encounters_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            try:
                encounter = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(encounter, dict)
                and encounter.get("owner_user_id", encounter.get("user_id")) == user_id
                and encounter.get("idempotency_key") == idempotency_key
            ):
                return encounter
        return None

    def list_encounters(self, user_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.encounters_path.exists():
            return []
        try:
            lines = self.encounters_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        encounters: list[dict[str, Any]] = []
        for line in lines:
            try:
                encounter = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(encounter, dict)
                and encounter.get("owner_user_id", encounter.get("user_id")) == user_id
            ):
                encounters.append(deepcopy(encounter))
        self._mark_read()
        if limit is not None:
            return encounters[-max(int(limit), 0):] if limit > 0 else []
        return encounters

    def list_candidates(self, user_id: str) -> list[dict[str, Any]]:
        return [food for food in self.list_foods(user_id) if food.get("status") == "candidate"]

    def save_encounter_idempotently(
        self,
        user_id: str,
        food: dict[str, Any],
        encounter: dict[str, Any],
    ) -> dict[str, Any]:
        with self._transaction_lock:
            key = str(encounter.get("idempotency_key") or "")
            existing = self.get_encounter_by_idempotency(user_id, key)
            if existing is not None:
                return {
                    "inserted": False,
                    "duplicate": True,
                    "food": self.get_food(user_id, str(existing.get("resolved_food_id") or "")),
                    "encounter": existing,
                }
            previous_master = self._read_master()
            stored_food = self.upsert_food(user_id, food)
            try:
                stored_encounter = self.append_encounter(user_id, encounter)
            except Exception as exc:
                self._write_master(previous_master)
                self._mark_error(exc)
                raise
            return {
                "inserted": True,
                "duplicate": False,
                "food": stored_food,
                "encounter": stored_encounter,
            }

    def get_repository_status(self) -> dict[str, Any]:
        status = super().get_repository_status()
        status.update(
            {
                "storage": "Local JSON",
                "migration_status": "local_only",
                "warning": "local MVP / durability is not guaranteed on Streamlit Cloud",
            }
        )
        return status
