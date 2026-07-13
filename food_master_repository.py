from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from food_master_models import FOOD_MASTER_VERSION, utc_now


class FoodMasterRepository(ABC):
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


class JsonFoodMasterRepository(FoodMasterRepository):
    """Local adapter; future database repositories can implement the same interface."""

    def __init__(self, master_path: Path, encounters_path: Path) -> None:
        self.master_path = Path(master_path)
        self.encounters_path = Path(encounters_path)

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
        return [
            deepcopy(food)
            for food in self._read_master()["foods"]
            if food.get("owner_user_id", food.get("user_id")) == user_id
        ]

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

    def list_candidates(self, user_id: str) -> list[dict[str, Any]]:
        return [food for food in self.list_foods(user_id) if food.get("status") == "candidate"]
