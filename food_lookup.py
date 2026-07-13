from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from food_aliases import normalize_food_name


FOOD_LOOKUP_VERSION = "1.0"
CATALOG_PATH = Path(__file__).with_name("food_lookup_catalog.json")


def _key(value: Any) -> str:
    return normalize_food_name(value).lower()


def _compact_key(value: Any) -> str:
    return _key(value).replace(" ", "")


def load_food_lookup_catalog() -> list[dict[str, Any]]:
    """Load the local, reviewed nutrition catalog without doing network I/O."""
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [deepcopy(item) for item in items if isinstance(item, dict)]


FOOD_LOOKUP_CATALOG = load_food_lookup_catalog()


def _empty_result(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "metadata": {"food_lookup_version": FOOD_LOOKUP_VERSION},
        "matched": False,
        "match": {"strategy": "unresolved", "confidence": "low", "reason": reason},
        "food": None,
        "nutrition": None,
        "source": None,
        "input": {
            "brand": item.get("brand"),
            "canonical_name": item.get("canonical_name"),
            "variant": item.get("variant"),
            "size": item.get("size"),
            "quantity": item.get("quantity"),
            "unit": item.get("unit"),
            "original_fragment": item.get("original_fragment") or item.get("raw_text"),
        },
    }


def _catalog_match(item: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, str] | None:
    input_name = item.get("canonical_name") or item.get("name") or item.get("raw_text")
    input_key = _key(input_name)
    input_compact = _compact_key(input_name)
    aliases = [candidate.get("canonical_name"), *candidate.get("aliases", [])]
    exact_aliases = {_key(alias) for alias in aliases if _key(alias)}
    compact_aliases = {_compact_key(alias) for alias in aliases if _compact_key(alias)}
    if input_key not in exact_aliases and input_compact not in compact_aliases:
        return None

    candidate_variant = candidate.get("variant")
    input_variant = item.get("variant")
    if candidate_variant != input_variant:
        return None

    candidate_size = candidate.get("size")
    input_size = item.get("size")
    if candidate_size is not None and candidate_size != input_size:
        return None

    original_fragment = item.get("original_fragment") or item.get("raw_text") or input_name
    original_key = _key(original_fragment)
    brand_aliases = {_key(candidate.get("brand")), *(_key(alias) for alias in candidate.get("brand_aliases", []))}
    if any(alias and alias in original_key for alias in brand_aliases):
        return ("brand_exact", "high")
    if input_key in exact_aliases:
        return ("canonical_exact", "high")
    return ("normalized_exact", "medium")


def lookup_food(item: dict[str, Any]) -> dict[str, Any]:
    """Resolve one parsed food item against the reviewed local catalog.

    The input is never modified. Explicit user-entered nutrition intentionally
    remains outside this function and retains priority in the calorie flow.
    """
    if not isinstance(item, dict):
        return _empty_result({}, "invalid_item")
    matches: list[tuple[str, str, dict[str, Any]]] = []
    for candidate in FOOD_LOOKUP_CATALOG:
        matched = _catalog_match(item, candidate)
        if matched:
            matches.append((matched[0], matched[1], candidate))

    if len(matches) != 1:
        return _empty_result(item, "not_found" if not matches else "ambiguous_catalog_match")

    strategy, confidence, candidate = matches[0]
    return {
        "metadata": {"food_lookup_version": FOOD_LOOKUP_VERSION},
        "matched": True,
        "match": {"strategy": strategy, "confidence": confidence, "reason": None},
        "food": {
            "id": candidate["id"],
            "brand": candidate.get("brand"),
            "canonical_name": candidate.get("canonical_name"),
            "variant": candidate.get("variant"),
            "size": candidate.get("size"),
        },
        "nutrition": deepcopy(candidate.get("nutrition")),
        "source": deepcopy(candidate.get("source")),
        "input": {
            "brand": item.get("brand"),
            "canonical_name": item.get("canonical_name"),
            "variant": item.get("variant"),
            "size": item.get("size"),
            "quantity": item.get("quantity"),
            "unit": item.get("unit"),
            "original_fragment": item.get("original_fragment") or item.get("raw_text"),
        },
    }


def lookup_parsed_foods(parsed_foods: dict[str, Any]) -> dict[str, Any]:
    """Look up parser output and return a new result object without mutation."""
    items = parsed_foods.get("items", []) if isinstance(parsed_foods, dict) else []
    results = [lookup_food(item) for item in items if isinstance(item, dict)]
    return {
        "metadata": {"food_lookup_version": FOOD_LOOKUP_VERSION},
        "items": results,
        "matched_count": sum(result["matched"] for result in results),
        "unmatched_count": sum(not result["matched"] for result in results),
    }
