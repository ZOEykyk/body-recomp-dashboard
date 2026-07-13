from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from food_master_models import normalized_identity_key
from food_master_repository import JsonFoodMasterRepository
from food_parser import parse_food_text
from food_source_models import explicit_user_label_source
from food_source_policy import select_nutrition_source
from personal_food_master import (
    create_food_from_encounter,
    personal_food_source_selection,
    promote_food,
    remember_food_encounters,
    resolve_personal_food,
    link_candidate_to_food,
)


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def main() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        repository = JsonFoodMasterRepository(root / "personal_food_master.json", root / "food_encounters.jsonl")
        assert_equal(repository.list_foods("user-a"), [], "empty repository")
        if (root / "personal_food_master.json").exists():
            raise AssertionError("read-only list_foods must not create storage")

        known = parse_food_text("ファミマ ファミチキ", "間食")
        known_before = deepcopy(known)
        known_encounters = remember_food_encounters(
            repository,
            "user-a",
            known,
            meal_type="間食",
            record_date="2026-07-13",
            operation_id="manual-save:2026-07-13",
            used_at="2026-07-13T09:00:00+00:00",
        )
        assert_equal(known, known_before, "encounter input mutation")
        assert_equal(len(known_encounters), 1, "known encounter stored")
        known_foods = repository.list_foods("user-a")
        assert_equal(len(known_foods), 1, "known food stored")
        assert_equal(known_foods[0]["status"], "active", "official encounter active")
        assert_equal(known_foods[0]["usage_count"], 1, "initial usage count")

        known_again = parse_food_text("ファミチキ", "間食")
        resolution = resolve_personal_food(known_again["items"][0], repository.list_foods("user-a"))
        assert_equal(resolution["status"], "matched", "personal identity reuse")
        remember_food_encounters(
            repository,
            "user-a",
            known_again,
            meal_type="間食",
            record_date="2026-07-14",
            operation_id="manual-save:2026-07-14",
            used_at="2026-07-14T09:00:00+00:00",
        )
        assert_equal(repository.list_foods("user-a")[0]["usage_count"], 2, "recurring usage count")

        unknown = parse_food_text("スターバックス GRAB&GO AROMA LATTE 500ml", "仕事中のドリンク")
        unknown_encounters = remember_food_encounters(
            repository,
            "user-a",
            unknown,
            meal_type="仕事中のドリンク",
            record_date="2026-07-15",
            operation_id="manual-save:2026-07-15",
            used_at="2026-07-15T09:00:00+00:00",
        )
        assert_equal(len(unknown_encounters), 1, "unknown encounter stored")
        candidates = repository.list_candidates("user-a")
        assert_equal(len(candidates), 1, "unknown remains candidate")
        assert_equal(candidates[0]["nutrition_sources"], [], "estimate not promoted to nutrition")

        for date in ("2026-07-16", "2026-07-17"):
            remember_food_encounters(
                repository,
                "user-a",
                unknown,
                meal_type="仕事中のドリンク",
                record_date=date,
                operation_id=f"manual-save:{date}",
                used_at=f"{date}T09:00:00+00:00",
            )
        candidates = repository.list_candidates("user-a")
        assert_equal(len(candidates), 1, "same unknown candidate deduplicated")
        assert_equal(candidates[0]["use_count"], 3, "candidate use count")

        repeated = remember_food_encounters(
            repository,
            "user-a",
            unknown,
            meal_type="仕事中のドリンク",
            record_date="2026-07-17",
            operation_id="manual-save:2026-07-17",
            used_at="2026-07-17T10:00:00+00:00",
        )
        assert_equal(repeated, [], "manual retry idempotency")
        assert_equal(repository.list_candidates("user-a")[0]["use_count"], 3, "retry must not increment use count")

        size_250 = parse_food_text("自作プロテインドリンク 250ml", "間食")
        size_500 = parse_food_text("自作プロテインドリンク 500ml", "間食")
        for index, parsed in enumerate((size_250, size_500), start=1):
            remember_food_encounters(
                repository,
                "user-a",
                parsed,
                meal_type="間食",
                record_date=f"2026-07-2{index}",
                operation_id=f"json-import:2026-07-2{index}",
                used_at=f"2026-07-2{index}T09:00:00+00:00",
            )
        candidate_sizes = [food.get("size") for food in repository.list_candidates("user-a")]
        if "250ml" not in candidate_sizes or "500ml" not in candidate_sizes:
            raise AssertionError("size variants must remain separate candidates")

        variant_base = {"metadata": {"food_parser_version": "1.0"}, "raw_text": "test", "items": []}
        for variant in ("バニラ", "チョコ"):
            parsed = deepcopy(variant_base)
            parsed["items"] = [{"canonical_name": "テストプロテイン", "variant": variant, "size": None, "quantity": 1, "unit": "個", "original_fragment": f"テストプロテイン {variant}", "explicit_nutrition": {}}]
            remember_food_encounters(
                repository,
                "user-a",
                parsed,
                meal_type="間食",
                record_date=f"2026-07-{22 if variant == 'バニラ' else 23}",
                operation_id=f"manual-save:{variant}",
                used_at="2026-07-22T09:00:00+00:00",
            )
        variants = [food.get("variant") for food in repository.list_candidates("user-a")]
        if "バニラ" not in variants or "チョコ" not in variants:
            raise AssertionError("food variants must remain separate candidates")

        alias_item = parse_food_text("スタバのアロマラテ", "仕事中のドリンク")["items"][0]
        explicit_selection = select_nutrition_source(
            [{"source": explicit_user_label_source(captured_at="2026-07-15"), "nutrition": {"basis": "per_item", "calories_kcal": 180}}]
        )
        personal_candidate = create_food_from_encounter("user-a", alias_item, explicit_selection, now="2026-07-15T10:00:00+00:00")
        personal_candidate["aliases"] = ["スタバのアロマラテ", "スターバックス AROMA LATTE"]
        repository.upsert_food("user-a", personal_candidate)
        assert_equal(repository.get_food("user-a", personal_candidate["food_id"])["status"], "candidate", "label stays candidate")

        promoted = promote_food(repository.get_food("user-a", personal_candidate["food_id"]), reviewer="user")
        repository.upsert_food("user-a", promoted)
        alias_resolution = resolve_personal_food(alias_item, repository.list_foods("user-a"))
        assert_equal(alias_resolution["status"], "matched", "promoted personal alias reuse")
        assert_equal(alias_resolution["food"]["review_status"], "reviewed", "promoted review status")

        source_selection = personal_food_source_selection(alias_resolution["food"])
        assert_equal(source_selection["selected"]["source"]["source_type"], "explicit_user_label", "personal source selection")

        linked = link_candidate_to_food(known_foods[0], repository.get_food("user-a", personal_candidate["food_id"]))
        assert_equal("スタバのアロマラテ" in linked["aliases"], True, "candidate linked to existing food")

        repository.archive_food("user-a", personal_candidate["food_id"])
        assert_equal(repository.get_food("user-a", personal_candidate["food_id"])["status"], "archived", "archive food")
        if not (root / "food_encounters.jsonl").read_text(encoding="utf-8").strip():
            raise AssertionError("encounters jsonl must contain appended encounters")

        first_encounter = next(json for json in (root / "food_encounters.jsonl").read_text(encoding="utf-8").splitlines() if json.startswith("{"))
        encounter = __import__("json").loads(first_encounter)
        required_encounter_fields = {
            "encounter_id", "idempotency_key", "owner_user_id", "record_date", "occurred_at", "meal_type",
            "original_text", "original_fragment", "parsed_identity", "resolved_food_id", "resolution_status",
            "selected_source_type", "selected_source_id", "selected_nutrition", "quantity", "unit", "parser_version",
            "lookup_version", "source_policy_version", "needs_review", "candidate_reason", "created_at", "schema_version",
        }
        if not required_encounter_fields.issubset(encounter):
            raise AssertionError("encounter contract incomplete")

        malformed = JsonFoodMasterRepository(root / "malformed.json", root / "malformed.jsonl")
        (root / "malformed.json").write_text("not-json", encoding="utf-8")
        (root / "malformed.jsonl").write_text("not-json\n", encoding="utf-8")
        assert_equal(malformed.list_foods("user-a"), [], "malformed master JSON safety")
        assert_equal(malformed.get_encounter_by_idempotency("user-a", "missing"), None, "malformed JSONL safety")

    if subprocess.run(["git", "diff", "--quiet", "--", "records.csv"], cwd=ROOT, check=False).returncode:
        raise AssertionError("records.csv must remain unchanged")
    if "food_master" in (ROOT / "records.csv").read_text(encoding="utf-8-sig").splitlines()[0]:
        raise AssertionError("CSV schema must not include Food Master fields")

    print("PR9 Personal Food Master validation passed")


if __name__ == "__main__":
    main()
