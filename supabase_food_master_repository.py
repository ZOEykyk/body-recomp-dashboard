from __future__ import annotations

from copy import deepcopy
import json
import logging
from typing import Any, Callable
from urllib import error, parse, request

from food_aliases import normalize_food_name
from food_master_models import normalized_identity_key, utc_now
from food_master_repository import FoodMasterRepository


LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 8.0
EXPECTED_SCHEMA_VERSION = "20260720.2"
ENCOUNTER_COLUMNS = {
    "encounter_id",
    "idempotency_key",
    "owner_user_id",
    "record_date",
    "occurred_at",
    "meal_type",
    "original_text",
    "original_fragment",
    "parsed_identity",
    "resolved_food_id",
    "resolution_status",
    "selected_source_type",
    "selected_source_id",
    "selected_nutrition",
    "resolution_origin",
    "resolution_confidence",
    "quantity",
    "unit",
    "parser_version",
    "lookup_version",
    "source_policy_version",
    "resolver_version",
    "needs_review",
    "candidate_reason",
    "created_at",
    "schema_version",
}


class SupabaseRepositoryError(RuntimeError):
    """Controlled storage error that never contains credentials."""


class SupabaseRestClient:
    """Small PostgREST client so app import does not require a Supabase SDK."""

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = max(float(timeout), 1.0)
        self.transport = transport or request.urlopen

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | list[dict[str, Any]] | None = None,
        prefer: str | None = None,
    ) -> Any:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {
            "apikey": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "bodyos-food-knowledge/1.0",
        }
        if not self.api_key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.api_key}"
        if prefer:
            headers["Prefer"] = prefer
        api_request = request.Request(f"{self.base_url}/rest/v1/{path.lstrip('/')}", data=data, method=method, headers=headers)
        try:
            with self.transport(api_request, timeout=self.timeout) as response:
                body = response.read()
                return json.loads(body.decode("utf-8")) if body else None
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise SupabaseRepositoryError(f"Supabase request failed ({exc.code}): {detail}") from exc
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise SupabaseRepositoryError(f"Supabase connection failed: {type(exc).__name__}") from exc


def _quoted(value: Any) -> str:
    return parse.quote(str(value), safe="")


def _food_identity_key(food: dict[str, Any]) -> str:
    return "|".join(normalized_identity_key(food))


def _food_row(user_id: str, food: dict[str, Any]) -> dict[str, Any]:
    usage_count = max(
        int(food.get("use_count") or 0),
        int(food.get("usage_count") or 0),
        0,
    )
    return {
        "food_id": food.get("food_id"),
        "owner_user_id": user_id,
        "scope": food.get("scope") or "personal",
        "brand": food.get("brand"),
        "canonical_name": food.get("canonical_name"),
        "variant": food.get("variant"),
        "size": food.get("size"),
        "identity_key": _food_identity_key(food),
        "category": food.get("category"),
        "default_quantity": food.get("default_quantity"),
        "default_unit": food.get("default_unit"),
        "notes": food.get("notes"),
        "status": food.get("status") or "candidate",
        "review_status": food.get("review_status") or "pending_review",
        "use_count": usage_count,
        "usage_count": usage_count,
        "first_used_at": food.get("first_used_at"),
        "last_used_at": food.get("last_used_at"),
        "created_at": food.get("created_at") or utc_now(),
        "updated_at": food.get("updated_at") or utc_now(),
        "schema_version": food.get("schema_version") or "1.1",
        "created_by": food.get("created_by") or "system",
        "updated_by": food.get("updated_by") or "system",
    }


def _alias_rows(user_id: str, food: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for alias in food.get("aliases") or []:
        normalized = normalize_food_name(alias).lower().strip()
        if not normalized:
            continue
        rows.append(
            {
                "food_id": food.get("food_id"),
                "owner_user_id": user_id,
                "alias": str(alias),
                "normalized_alias": normalized,
                "language": "ja",
                "confidence": "high",
                "review_status": food.get("review_status") or "pending_review",
            }
        )
    return rows


def _source_rows(food: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for candidate in food.get("nutrition_sources") or []:
        if not isinstance(candidate, dict):
            continue
        source = deepcopy(candidate.get("source") or {})
        nutrition = deepcopy(candidate.get("nutrition") or {})
        source_id = source.get("source_id")
        if not source_id:
            continue
        sources.append(
            {
                "source_id": source_id,
                "food_id": food.get("food_id"),
                "source_type": source.get("source_type"),
                "publisher": source.get("publisher"),
                "source_ref": source.get("source_ref"),
                "captured_at": source.get("captured_at"),
                "verified_at": source.get("verified_at"),
                "valid_from": source.get("valid_from"),
                "valid_to": source.get("valid_to"),
                "product_version": source.get("product_version"),
                "reviewer": source.get("reviewer"),
                "verification_status": source.get("verification_status") or "pending_review",
                "confidence": source.get("confidence") or "low",
                "notes": source.get("notes"),
            }
        )
        facts.append(
            {
                "source_id": source_id,
                "food_id": food.get("food_id"),
                "basis": nutrition.get("basis") or "unknown",
                "serving_quantity": nutrition.get("serving_quantity"),
                "serving_unit": nutrition.get("serving_unit"),
                "calories_kcal": nutrition.get("calories_kcal"),
                "protein_g": nutrition.get("protein_g"),
                "fat_g": nutrition.get("fat_g"),
                "carbs_g": nutrition.get("carbs_g"),
                "sugar_g": nutrition.get("sugar_g"),
                "fiber_g": nutrition.get("fiber_g"),
                "salt_g": nutrition.get("salt_g"),
            }
        )
    return sources, facts


def _rpc_food_payload(user_id: str, food: dict[str, Any]) -> dict[str, Any]:
    sources, facts = _source_rows(food)
    return {
        "food": _food_row(user_id, food),
        "aliases": _alias_rows(user_id, food),
        "nutrition_sources": sources,
        "nutrition_facts": facts,
    }


def _encounter_row(user_id: str, encounter: dict[str, Any]) -> dict[str, Any]:
    """Keep legacy JSON fields out of the normalized PostgREST contract."""
    row = {key: deepcopy(value) for key, value in encounter.items() if key in ENCOUNTER_COLUMNS}
    row["owner_user_id"] = user_id
    return row


def _hydrate_foods(
    food_rows: list[dict[str, Any]],
    aliases: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    aliases_by_food: dict[str, list[str]] = {}
    for alias in aliases:
        aliases_by_food.setdefault(str(alias.get("food_id")), []).append(str(alias.get("alias") or ""))
    facts_by_source = {
        (str(fact.get("food_id")), str(fact.get("source_id"))): fact
        for fact in facts
    }
    sources_by_food: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        source_id = str(source.get("source_id") or "")
        food_id = str(source.get("food_id") or "")
        nutrition = deepcopy(facts_by_source.get((food_id, source_id)) or {})
        for key in ("nutrition_fact_id", "source_id", "food_id", "created_at", "updated_at"):
            nutrition.pop(key, None)
        source_value = deepcopy(source)
        for key in ("food_id", "created_at", "updated_at"):
            source_value.pop(key, None)
        sources_by_food.setdefault(str(source.get("food_id")), []).append(
            {"source": source_value, "nutrition": nutrition}
        )
    hydrated = []
    for row in food_rows:
        food = deepcopy(row)
        food.pop("identity_key", None)
        food["user_id"] = food.get("owner_user_id")
        food_id = str(food.get("food_id") or "")
        food["aliases"] = [alias for alias in aliases_by_food.get(food_id, []) if alias]
        food["nutrition_sources"] = sources_by_food.get(food_id, [])
        hydrated.append(food)
    return hydrated


class SupabaseFoodMasterRepository(FoodMasterRepository):
    """Supabase/PostgREST implementation of the Food Knowledge repository."""

    def __init__(self, client: SupabaseRestClient) -> None:
        super().__init__()
        self.client = client
        self._schema_version: str | None = None

    def health_check(self) -> None:
        try:
            result = self.client.request("POST", "rpc/food_knowledge_schema_version_v1", payload={})
            value = result[0] if isinstance(result, list) and result else result
            if str(value or "") != EXPECTED_SCHEMA_VERSION:
                raise SupabaseRepositoryError("Supabase Food Knowledge schema version mismatch")
            self._schema_version = str(value)
            self._mark_read()
        except Exception as exc:
            self._mark_error(exc)
            raise

    def _select(self, table: str, query: str) -> list[dict[str, Any]]:
        try:
            result = self.client.request("GET", f"{table}?{query}")
            self._mark_read()
            return [row for row in (result or []) if isinstance(row, dict)]
        except Exception as exc:
            self._mark_error(exc)
            raise

    def _foods_for_rows(self, user_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        food_ids = [str(row.get("food_id")) for row in rows if row.get("food_id")]
        if not food_ids:
            return []
        in_filter = ",".join(_quoted(food_id) for food_id in food_ids)
        aliases = self._select("food_aliases", f"select=*&food_id=in.({in_filter})&owner_user_id=eq.{_quoted(user_id)}")
        sources = self._select("nutrition_sources", f"select=*&food_id=in.({in_filter})")
        facts = self._select("nutrition_facts", f"select=*&food_id=in.({in_filter})")
        return _hydrate_foods(rows, aliases, sources, facts)

    def list_foods(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._select("foods", f"select=*&owner_user_id=eq.{_quoted(user_id)}&order=updated_at.desc")
        return self._foods_for_rows(user_id, rows)

    def get_food(self, user_id: str, food_id: str) -> dict[str, Any] | None:
        rows = self._select(
            "foods",
            f"select=*&owner_user_id=eq.{_quoted(user_id)}&food_id=eq.{_quoted(food_id)}&limit=1",
        )
        foods = self._foods_for_rows(user_id, rows)
        return foods[0] if foods else None

    def upsert_food(self, user_id: str, food: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.client.request(
                "POST",
                "rpc/upsert_food_knowledge_v1",
                payload={"p_owner_user_id": user_id, "p_food_payload": _rpc_food_payload(user_id, food)},
            )
            self._mark_write()
            value = result[0] if isinstance(result, list) and result else result
            stored = (value or {}).get("food") or food
            return self.get_food(user_id, str(stored.get("food_id") or food.get("food_id"))) or deepcopy(food)
        except Exception as exc:
            self._mark_error(exc)
            raise

    def archive_food(self, user_id: str, food_id: str) -> None:
        food = self.get_food(user_id, food_id)
        if food is None:
            return
        food["status"] = "archived"
        food["updated_at"] = utc_now()
        self.upsert_food(user_id, food)

    def append_encounter(self, user_id: str, encounter: dict[str, Any]) -> dict[str, Any]:
        payload = _encounter_row(user_id, encounter)
        try:
            result = self.client.request(
                "POST",
                "food_encounters?on_conflict=owner_user_id,idempotency_key",
                payload=payload,
                prefer="resolution=ignore-duplicates,return=representation",
            )
            self._mark_write()
            if isinstance(result, list) and result:
                return deepcopy(result[0])
            existing = self.get_encounter_by_idempotency(user_id, str(payload.get("idempotency_key") or ""))
            return existing or payload
        except Exception as exc:
            self._mark_error(exc)
            raise

    def get_encounter_by_idempotency(self, user_id: str, idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        rows = self._select(
            "food_encounters",
            f"select=*&owner_user_id=eq.{_quoted(user_id)}&idempotency_key=eq.{_quoted(idempotency_key)}&limit=1",
        )
        return deepcopy(rows[0]) if rows else None

    def list_candidates(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._select(
            "foods",
            f"select=*&owner_user_id=eq.{_quoted(user_id)}&status=eq.candidate&order=updated_at.desc",
        )
        return self._foods_for_rows(user_id, rows)

    def list_encounters(self, user_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        query = f"select=*&owner_user_id=eq.{_quoted(user_id)}&order=created_at.asc"
        if limit is not None:
            query += f"&limit={max(int(limit), 0)}"
        return deepcopy(self._select("food_encounters", query))

    def find_food_candidates(self, user_id: str, identity: dict[str, Any]) -> list[dict[str, Any]]:
        identity_key = _food_identity_key(identity)
        rows = self._select(
            "foods",
            f"select=*&owner_user_id=eq.{_quoted(user_id)}&identity_key=eq.{_quoted(identity_key)}&status=neq.archived",
        )
        return self._foods_for_rows(user_id, rows)

    def find_by_alias(self, user_id: str, normalized_alias: str) -> list[dict[str, Any]]:
        aliases = self._select(
            "food_aliases",
            f"select=food_id&owner_user_id=eq.{_quoted(user_id)}&normalized_alias=eq.{_quoted(normalized_alias)}",
        )
        food_ids = [str(alias.get("food_id")) for alias in aliases if alias.get("food_id")]
        if not food_ids:
            return []
        in_filter = ",".join(_quoted(food_id) for food_id in food_ids)
        rows = self._select("foods", f"select=*&owner_user_id=eq.{_quoted(user_id)}&food_id=in.({in_filter})")
        return self._foods_for_rows(user_id, rows)

    def list_active_foods(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._select(
            "foods",
            f"select=*&owner_user_id=eq.{_quoted(user_id)}&status=eq.active&order=updated_at.desc",
        )
        return self._foods_for_rows(user_id, rows)

    def list_recent_foods(self, user_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = self._select(
            "foods",
            f"select=*&owner_user_id=eq.{_quoted(user_id)}&status=neq.archived&order=updated_at.desc&limit={max(int(limit), 0)}",
        )
        return self._foods_for_rows(user_id, rows)

    def list_top_used_foods(self, user_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = self._select(
            "foods",
            f"select=*&owner_user_id=eq.{_quoted(user_id)}&status=neq.archived&order=usage_count.desc,last_used_at.desc&limit={max(int(limit), 0)}",
        )
        return self._foods_for_rows(user_id, rows)

    def build_snapshot(self, user_id: str, *, include_encounters: bool = False) -> dict[str, Any]:
        """Build Resolver knowledge from active rows without scanning candidates."""
        return {
            "repository_type": type(self).__name__,
            "user_id": user_id,
            "personal_foods": self.list_active_foods(user_id),
            "encounters": self.list_encounters(user_id) if include_encounters else [],
        }

    def save_encounter_idempotently(
        self,
        user_id: str,
        food: dict[str, Any],
        encounter: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            result = self.client.request(
                "POST",
                "rpc/save_food_encounter_v1",
                payload={
                    "p_owner_user_id": user_id,
                    "p_food_payload": _rpc_food_payload(user_id, food),
                    "p_encounter": _encounter_row(user_id, encounter),
                },
            )
            self._mark_write()
            value = result[0] if isinstance(result, list) and result else result
            value = value if isinstance(value, dict) else {}
            stored_food = value.get("food") or food
            stored_encounter = value.get("encounter") or encounter
            hydrated_food = self.get_food(
                user_id,
                str(stored_food.get("food_id") or food.get("food_id") or ""),
            ) or deepcopy(food)
            return {
                "inserted": bool(value.get("inserted")),
                "duplicate": not bool(value.get("inserted")),
                "food": hydrated_food,
                "encounter": deepcopy(stored_encounter),
            }
        except Exception as exc:
            self._mark_error(exc)
            raise

    def get_repository_status(self) -> dict[str, Any]:
        status = super().get_repository_status()
        status.update(
            {
                "storage": "Supabase",
                "migration_status": self._schema_version or "unknown",
                "warning": None,
            }
        )
        return status


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "EXPECTED_SCHEMA_VERSION",
    "SupabaseFoodMasterRepository",
    "SupabaseRepositoryError",
    "SupabaseRestClient",
]
