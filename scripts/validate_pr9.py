from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from food_master_models import new_food_record
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
            repository, "user-a", known, meal_type="間食", used_at="2026-07-13T09:00:00+00:00"
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
            repository, "user-a", known_again, meal_type="間食", used_at="2026-07-14T09:00:00+00:00"
        )
        assert_equal(repository.list_foods("user-a")[0]["usage_count"], 2, "recurring usage count")

        unknown = parse_food_text("スターバックス GRAB&GO AROMA LATTE 500ml", "仕事中のドリンク")
        unknown_encounters = remember_food_encounters(
            repository, "user-a", unknown, meal_type="仕事中のドリンク", used_at="2026-07-15T09:00:00+00:00"
        )
        assert_equal(len(unknown_encounters), 1, "unknown encounter stored")
        candidates = repository.list_candidates("user-a")
        assert_equal(len(candidates), 1, "unknown remains candidate")
        assert_equal(candidates[0]["nutrition_sources"], [], "estimate not promoted to nutrition")

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

        repository.archive_food("user-a", personal_candidate["food_id"])
        assert_equal(repository.get_food("user-a", personal_candidate["food_id"])["status"], "archived", "archive food")
        if not (root / "food_encounters.jsonl").read_text(encoding="utf-8").strip():
            raise AssertionError("encounters jsonl must contain appended encounters")

    if subprocess.run(["git", "diff", "--quiet", "--", "records.csv"], cwd=ROOT, check=False).returncode:
        raise AssertionError("records.csv must remain unchanged")
    if "food_master" in (ROOT / "records.csv").read_text(encoding="utf-8-sig").splitlines()[0]:
        raise AssertionError("CSV schema must not include Food Master fields")

    print("PR9 Personal Food Master validation passed")


if __name__ == "__main__":
    main()
