from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from food_master_repository import JsonFoodMasterRepository
from supabase_food_master_repository import SupabaseFoodMasterRepository, SupabaseRestClient


def _malformed_jsonl_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    errors = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [{"line": None, "error": type(exc).__name__}]
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"line": number, "error": f"JSONDecodeError at column {exc.colno}"})
            continue
        if not isinstance(value, dict):
            errors.append({"line": number, "error": "Encounter must be an object"})
    return errors


def build_migration_report(
    master_path: Path,
    encounters_path: Path,
    user_id: str,
    *,
    target: SupabaseFoodMasterRepository | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    local = JsonFoodMasterRepository(master_path, encounters_path)
    foods = local.list_foods(user_id)
    encounters = local.list_encounters(user_id)
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "owner_user_id": user_id,
        "source": {
            "master_path": str(master_path),
            "encounters_path": str(encounters_path),
            "foods": len(foods),
            "encounters": len(encounters),
            "malformed_encounter_lines": _malformed_jsonl_lines(encounters_path),
        },
        "target_before": None,
        "result": {"foods_upserted": 0, "encounters_saved": 0, "duplicates_skipped": 0, "errors": []},
        "target_after": None,
    }
    if not apply:
        return report
    if target is None:
        raise ValueError("Supabase target is required in apply mode")

    before_foods = target.list_foods(user_id)
    before_encounters = target.list_encounters(user_id)
    report["target_before"] = {"foods": len(before_foods), "encounters": len(before_encounters)}

    valid_food_ids: set[str] = set()
    for food in foods:
        try:
            stored = target.upsert_food(user_id, food)
            valid_food_ids.add(str(stored.get("food_id") or food.get("food_id")))
            report["result"]["foods_upserted"] += 1
        except Exception as exc:
            report["result"]["errors"].append(
                {"type": "food", "id": food.get("food_id"), "error": type(exc).__name__}
            )

    for encounter in encounters:
        resolved_food_id = str(encounter.get("resolved_food_id") or "")
        if resolved_food_id and resolved_food_id not in valid_food_ids and target.get_food(user_id, resolved_food_id) is None:
            report["result"]["errors"].append(
                {"type": "encounter", "id": encounter.get("encounter_id"), "error": "resolved food missing"}
            )
            continue
        try:
            key = str(encounter.get("idempotency_key") or "")
            if target.get_encounter_by_idempotency(user_id, key) is not None:
                report["result"]["duplicates_skipped"] += 1
                continue
            target.append_encounter(user_id, encounter)
            report["result"]["encounters_saved"] += 1
        except Exception as exc:
            report["result"]["errors"].append(
                {"type": "encounter", "id": encounter.get("encounter_id"), "error": type(exc).__name__}
            )

    after_foods = target.list_foods(user_id)
    after_encounters = target.list_encounters(user_id)
    report["target_after"] = {"foods": len(after_foods), "encounters": len(after_encounters)}
    report["comparison"] = {
        "food_count_matches": len(after_foods) >= len(foods),
        "encounter_count_matches": len(after_encounters) >= len(encounters) - len(report["result"]["errors"]),
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate BodyOS Food Knowledge JSON/JSONL to Supabase.")
    parser.add_argument("--master", type=Path, default=ROOT / "personal_food_master.json")
    parser.add_argument("--encounters", type=Path, default=ROOT / "food_encounters.jsonl")
    parser.add_argument("--user-id", default=os.environ.get("FOOD_KNOWLEDGE_USER_ID", "local-default"))
    parser.add_argument("--apply", action="store_true", help="Write to Supabase. Default is dry-run.")
    parser.add_argument("--report", type=Path, help="Optional JSON report output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = None
    if args.apply:
        url = os.environ.get("SUPABASE_URL", "").strip()
        service_key = (
            os.environ.get("SUPABASE_SECRET_KEY", "").strip()
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
        if not url or not service_key:
            print("SUPABASE_URL and a Supabase secret/service-role key are required for --apply.", file=sys.stderr)
            return 2
        target = SupabaseFoodMasterRepository(SupabaseRestClient(url, service_key))
        target.health_check()
    report = build_migration_report(
        args.master,
        args.encounters,
        args.user_id,
        target=target,
        apply=args.apply,
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    return 1 if report["result"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
