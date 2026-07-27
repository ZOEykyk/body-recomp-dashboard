from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from food_master_models import new_food_record  # noqa: E402
from food_master_repository import JsonFoodMasterRepository  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    before = hashlib.sha256((ROOT / "records.csv").read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory() as directory:
        repository = JsonFoodMasterRepository(
            Path(directory) / "foods.json",
            Path(directory) / "encounters.jsonl",
        )
        first = new_food_record(
            "user-1",
            {"canonical_name": "アロマラテ", "original_fragment": "アロマラテ"},
            status="active",
            review_status="reviewed",
        )
        second = new_food_record(
            "user-1",
            {"canonical_name": "別商品", "original_fragment": "別商品"},
            status="active",
            review_status="reviewed",
        )
        repository.upsert_food("user-1", first)
        repository.upsert_food("user-1", second)

        stored = repository.add_alias(
            "user-1",
            first["food_id"],
            "  ＡＲＯＭＡ　ＬＡＴＴＥ  ",
            source="ai_suggestion",
            ai_model="test-model",
            approved_by_user=True,
        )
        check("AROMA LATTE" in stored["aliases"], "NFKC and whitespace normalization")
        metadata = next(item for item in stored["alias_metadata"] if item["alias"] == "AROMA LATTE")
        check(metadata["source"] == "ai_suggestion", "alias source is retained")
        check(metadata["ai_model"] == "test-model", "AI model provenance is retained")
        check(metadata["approved_by_user"] is True, "only approved alias is stored")
        matches = repository.find_by_alias("user-1", "aroma latte")
        check([food["food_id"] for food in matches] == [first["food_id"]], "approved alias lookup")

        try:
            repository.add_alias(
                "user-1",
                second["food_id"],
                "AROMA LATTE",
                approved_by_user=True,
            )
        except ValueError:
            print("PASS: one owner alias cannot point to two foods")
        else:
            raise AssertionError("duplicate alias assignment must fail")

        try:
            repository.add_alias(
                "user-1",
                first["food_id"],
                "未承認候補",
                source="ai_suggestion",
                ai_model="test-model",
                approved_by_user=False,
            )
        except ValueError:
            print("PASS: unapproved AI proposal is not persisted")
        else:
            raise AssertionError("unapproved alias must fail")

        foods = repository.list_foods("user-1")
        check(len(foods) == 2, "alias handling does not auto-merge foods")
        check(not repository.find_by_alias("user-1", "未承認候補"), "unapproved proposal is not searchable")

    migration = (ROOT / "supabase/migrations/20260727_pr13_food_alias.sql").read_text(encoding="utf-8")
    check("food_aliases_owner_alias_uidx" in migration, "Supabase owner alias uniqueness migration")
    check("upsert_food_alias_v1" in migration, "Supabase approved alias RPC")
    after = hashlib.sha256((ROOT / "records.csv").read_bytes()).hexdigest()
    check(before == after, "records.csv is unchanged")
    print("PR13 alias validation passed.")


if __name__ == "__main__":
    main()
