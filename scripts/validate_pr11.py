from __future__ import annotations

from copy import deepcopy
import datetime as dt
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from validate_pr8_2 import install_fake_streamlit

install_fake_streamlit()

from food_knowledge_dashboard import food_knowledge_metrics
from food_master_models import new_food_record
from food_master_repository import JsonFoodMasterRepository
from food_parser import parse_food_text
from food_resolver import build_food_knowledge_snapshot, resolve_food_text
from food_source_policy import FOOD_RESOLUTION_PRIORITY
from nutrition_intelligence import analyze_nutrition
from workout_intelligence import analyze_workout


AS_OF = dt.date(2026, 7, 20)


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value: bool, label: str) -> None:
    if not value:
        raise AssertionError(label)


def source(source_type: str, source_id: str) -> dict:
    return {
        "source_id": source_id,
        "source_type": source_type,
        "publisher": "BodyOS Validation",
        "source_ref": "local-validation",
        "captured_at": "2026-07-20",
        "verified_at": "2026-07-20",
        "valid_from": "2026-01-01",
        "valid_to": None,
        "product_version": "validation-v1",
        "reviewer": "BodyOS",
        "verification_status": "verified",
        "confidence": "high",
        "notes": None,
    }


def nutrition(kcal: float, protein: float | None = None) -> dict:
    return {
        "basis": "per_item",
        "calories_kcal": kcal,
        "protein_g": protein,
        "fat_g": None,
        "carbs_g": None,
        "sugar_g": None,
        "fiber_g": None,
        "salt_g": None,
    }


def personal_famichiki() -> dict:
    item = parse_food_text("ファミマ ファミチキ", "間食")["items"][0]
    food = new_food_record(
        "user-a",
        item,
        status="active",
        review_status="reviewed",
        nutrition_sources=[
            {
                "source": source("user_verified", "personal-famichiki"),
                "nutrition": nutrition(333, 30),
            }
        ],
        now="2026-07-20T00:00:00+00:00",
    )
    food["aliases"] = ["ファミチキ", "ファミマ ファミチキ"]
    return food


def main() -> None:
    assert_equal(
        list(FOOD_RESOLUTION_PRIORITY),
        ["explicit", "personal", "official", "generic", "fallback"],
        "shared resolution priority",
    )

    personal = personal_famichiki()
    knowledge = build_food_knowledge_snapshot([personal])
    knowledge_before = deepcopy(knowledge)
    personal_result = resolve_food_text("ファミチキ", "間食", knowledge=knowledge, as_of=AS_OF)
    assert_equal(personal_result["items"][0]["selected_origin"], "personal", "personal beats official")
    assert_equal(personal_result["kcal"], 333, "personal nutrition selected")
    assert_equal(knowledge, knowledge_before, "resolver knowledge input mutation")

    explicit = resolve_food_text(
        "ファミチキ 223kcal P12g F15g C14g",
        "間食",
        knowledge=knowledge,
        as_of=AS_OF,
    )
    assert_equal(explicit["resolution_counts"]["explicit"], 1, "explicit beats personal")
    assert_equal(explicit["kcal"], 223, "explicit calories preserved")

    official = resolve_food_text("ファミチキ2個", "間食", as_of=AS_OF)
    assert_equal(official["items"][0]["selected_origin"], "official", "official beats generic")
    assert_equal(official["kcal"], 503, "official quantity total")

    generic = resolve_food_text("納豆", "昼", as_of=AS_OF)
    assert_equal(generic["items"][0]["selected_origin"], "generic", "generic catalog")
    assert_equal(generic["kcal"], 90, "generic calories")

    fallback = resolve_food_text("おばあちゃん特製の謎料理", "夜", as_of=AS_OF)
    assert_equal(fallback["items"][0]["selected_origin"], "fallback", "fallback last")
    assert_equal(fallback["kcal"], 850, "meal fallback compatibility")

    breakfast = resolve_food_text("ソーセージエッグマフィン、ハッシュポテト、アイスコーヒー", "朝", as_of=AS_OF)
    lunch = resolve_food_text("ベーグル、卵1個、有塩バター7g、納豆、ジョンソンヴィル", "昼", as_of=AS_OF)
    dinner = resolve_food_text("舞茸おにぎり、納豆、SAVAS、理想のトマト", "夜", as_of=AS_OF)
    assert_equal((breakfast["kcal"], lunch["kcal"], dinner["kcal"]), (644, 652, 490), "PR6.2 meal compatibility")
    assert_true(1750 <= breakfast["kcal"] + lunch["kcal"] + dinner["kcal"] <= 1900, "daily calorie credibility")

    record = {
        "日付": "2026-07-20",
        "朝": "ファミチキ",
        "昼": "",
        "夜": "",
        "推定摂取カロリー": 333,
        "day_completion_state": "morning_only",
    }
    record_before = deepcopy(record)
    nutrition_result = analyze_nutrition(record, food_knowledge=knowledge)
    assert_equal(record, record_before, "nutrition record input mutation")
    assert_equal(knowledge, knowledge_before, "nutrition knowledge input mutation")
    assert_equal(
        nutrition_result["data_quality"]["resolution_origin_distribution"].get("personal"),
        1,
        "Nutrition Intelligence uses personal resolver result",
    )

    import app

    normalized = app.normalize_record(
        {"date": "2026-07-20", "breakfast": "ファミチキ2個", "workout": False}
    )
    assert_equal(set(normalized), set(app.COLUMNS), "JSON import schema unchanged")
    assert_equal(normalized["朝カロリー(kcal)"], 503, "JSON import uses shared resolver")
    workout = analyze_workout({"筋トレ有無": "あり", "筋トレ内容": "ベンチプレス 90kg×5×4"})
    assert_true(workout["performed"] and "exercises" in workout, "Workout Intelligence unchanged")

    with TemporaryDirectory() as directory:
        root = Path(directory)
        repository = JsonFoodMasterRepository(root / "personal.json", root / "encounters.jsonl")
        original_repository = app.PERSONAL_FOOD_REPOSITORY
        app.PERSONAL_FOOD_REPOSITORY = repository
        try:
            official_detail = app.estimate_calorie_detail("ファミチキ", "間食")
            fallback_detail = app.estimate_calorie_detail("未知の軽食", "間食")
            summary = app.remember_saved_meals(
                [
                    ("間食", "ファミチキ", official_detail),
                    ("夜", "未知の軽食", fallback_detail),
                ],
                record_date="2026-07-20",
                operation_id="json-import:2026-07-20",
                used_at="2026-07-20T00:00:00+00:00",
            )
        finally:
            app.PERSONAL_FOOD_REPOSITORY = original_repository
        assert_equal(summary["official"], 1, "JSON import official summary")
        assert_equal(summary["fallback"], 1, "JSON import fallback summary")
        assert_equal(summary["encounter_count"], 2, "JSON import encounter summary")
        snapshot = repository.get_knowledge_snapshot("local-default", include_encounters=True)
        assert_equal(len(snapshot["encounters"]), 2, "repository encounter snapshot")
        metrics = food_knowledge_metrics(repository, "local-default")
        assert_equal(metrics["fallback_count"], 1, "Food Knowledge fallback metric")
        assert_true(metrics["registered_count"] >= metrics["official_count"], "Food Knowledge registered metric")

    direct_lookup_imports = subprocess.run(
        ["rg", "-n", "from food_lookup import .*lookup_food|lookup_food\\(", "app.py", "nutrition_intelligence.py", "personal_food_master.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert_equal(direct_lookup_imports.returncode, 1, "no alternate lookup path in consumers")
    if subprocess.run(["git", "diff", "--quiet", "--", "records.csv"], cwd=ROOT, check=False).returncode:
        raise AssertionError("records.csv must remain unchanged")
    header = (ROOT / "records.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert_true("food_resolver" not in header and "food_master" not in header, "CSV schema unchanged")
    print("PR11 Food Knowledge Foundation validation passed")


if __name__ == "__main__":
    main()
