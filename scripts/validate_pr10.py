from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nutrition_intelligence import analyze_nutrition


def assert_true(value: bool, label: str) -> None:
    if not value:
        raise AssertionError(label)


def complete_record(**overrides):
    record = {
        "日付": "2026-07-12",
        "朝": "223kcal P25g F6g C20g サラダ",
        "昼": "700kcal P45g F20g C80g 温野菜",
        "夜": "1100kcal P65g F40g C130g 海藻",
        "推定摂取カロリー": 2023,
        "protein_g": 135,
        "fat_g": 66,
        "carbs_g": 230,
        "fiber_g": 22,
        "salt_g": 6,
        "hydration_ml": 2000,
    }
    record.update(overrides)
    return record


def main() -> None:
    profile = {"body_weight": 80, "goal": "recomposition"}
    balanced = complete_record()
    before = deepcopy(balanced)
    result = analyze_nutrition(balanced, profile=profile)
    assert_true(balanced == before, "record must not mutate")
    assert_true(result["status"] == "complete_day" and result["score"] >= 80, "balanced complete day")
    assert_true(any(item["code"] == "protein_on_track" for item in result["strengths"]), "protein strength")
    assert_true(len(result["actions"]) <= 3, "top three actions cap")

    partial = complete_record(**{"日付": "2026-07-14", "夜": "", "推定摂取カロリー": 1100, "protein_g": 75, "fat_g": 35, "carbs_g": 120})
    partial_result = analyze_nutrition(partial, profile=profile, now=__import__("datetime").datetime(2026, 7, 14, 13))
    assert_true(partial_result["status"] == "partial_day", "partial-day status")
    assert_true("夕食" in partial_result["summary"] or "現時点" in partial_result["summary"], "partial-day cautious wording")

    morning = complete_record(**{"日付": "2026-07-14", "昼": "", "夜": "", "推定摂取カロリー": 300, "protein_g": 25, "fat_g": 8, "carbs_g": 30})
    morning_result = analyze_nutrition(morning, profile=profile, now=__import__("datetime").datetime(2026, 7, 14, 8))
    assert_true(morning_result["status"] == "morning_only", "morning-only status")

    high_calorie = complete_record(**{"推定摂取カロリー": 3700, "protein_g": 140, "fat_g": 130, "carbs_g": 390})
    high_result = analyze_nutrition(high_calorie, profile=profile)
    assert_true(any(item["code"] == "calories_high" for item in high_result["priorities"]), "high-calorie priority")
    assert_true(not any("補う" in item["title"] for item in high_result["actions"]), "no contradictory calorie action")

    low_protein = complete_record(**{"protein_g": 45, "fat_g": 60, "carbs_g": 250})
    low_protein_result = analyze_nutrition(low_protein, profile=profile)
    assert_true(any(item["code"] == "protein_low" for item in low_protein_result["priorities"]), "low-protein priority")

    high_fat_partial = complete_record(**{"日付": "2026-07-14", "夜": "", "fat_g": 95, "推定摂取カロリー": 1400, "protein_g": 80, "carbs_g": 100})
    high_fat_result = analyze_nutrition(high_fat_partial, profile=profile, now=__import__("datetime").datetime(2026, 7, 14, 14))
    assert_true(any(item["code"] == "fat_high" for item in high_fat_result["priorities"]), "high-fat partial priority")

    protein_snack = complete_record(**{"間食": "オイコス PRO 100kcal P15g F0g C10g", "間食カロリー(kcal)": 100})
    snack_result = analyze_nutrition(protein_snack, profile=profile)
    assert_true(snack_result["snacks"]["supportive"], "protein snack is supportive")
    assert_true(not any(item["code"] == "snack_high" for item in snack_result["priorities"]), "supportive snack not negative")

    discretionary = complete_record(**{"間食": "アイス 700kcal", "間食カロリー(kcal)": 700, "推定摂取カロリー": 2500})
    discretionary_result = analyze_nutrition(discretionary, profile=profile)
    assert_true(any(item["code"] == "snack_high" for item in discretionary_result["priorities"]), "high discretionary snack")

    unknown = {"日付": "2026-07-12", "朝": "おばあちゃん特製カレー", "昼": "", "夜": "", "推定摂取カロリー": 650}
    unknown_result = analyze_nutrition(unknown, profile=profile)
    assert_true(unknown_result["confidence"]["level"] == "low" and unknown_result["data_quality"]["unresolved_item_count"] >= 1, "unknown meal lowers confidence")

    calories_only = {"日付": "2026-07-12", "朝": "", "昼": "", "夜": "", "推定摂取カロリー": 2100, "day_completion_state": "complete_day"}
    calories_only_result = analyze_nutrition(calories_only, profile=profile)
    assert_true(calories_only_result["score_breakdown"]["protein"]["status"] == "unavailable", "missing macros unavailable")
    assert_true(calories_only_result["available_points"] < 100, "unavailable metrics normalized")
    assert_true(calories_only_result["score_breakdown"]["fiber"]["status"] == "unavailable", "fiber unavailable")
    assert_true(calories_only_result["score_breakdown"]["hydration"]["status"] == "unavailable", "hydration unavailable")

    vegetable_light = complete_record(**{"朝": "理想のトマト 70kcal", "昼": "700kcal P45g F20g C80g", "夜": "1100kcal P65g F40g C130g"})
    vegetable_result = analyze_nutrition(vegetable_light, profile=profile)
    assert_true(any(item["code"] == "vegetables_low" for item in vegetable_result["priorities"]), "tomato juice alone is insufficient")

    yesterday = complete_record(**{"日付": "2026-07-11", "protein_g": 55})
    comparison_result = analyze_nutrition(balanced, history=[yesterday], profile=profile)
    assert_true(comparison_result["comparisons"]["previous_day"]["available"], "previous-day comparison")
    history = [complete_record(**{"日付": f"2026-07-0{day}"}) for day in range(5, 12)]
    seven_result = analyze_nutrition(balanced, history=history, profile=profile)
    assert_true(seven_result["comparisons"]["seven_day"]["available"], "seven-day average")

    explicit_result = analyze_nutrition(complete_record(), profile=profile)
    assert_true(explicit_result["confidence"]["score"] >= .55, "explicit-label-heavy confidence")
    fallback_result = analyze_nutrition({"日付": "2026-07-12", "朝": "謎の丼", "昼": "不明な定食", "夜": "おばあちゃん特製カレー"}, profile=profile)
    assert_true(fallback_result["confidence"]["level"] == "low", "fallback-heavy confidence")

    history_before = deepcopy(history)
    profile_before = deepcopy(profile)
    analyze_nutrition(balanced, history=history, profile=profile)
    assert_true(history == history_before and profile == profile_before, "history/profile must not mutate")
    if subprocess.run(["git", "diff", "--quiet", "--", "records.csv"], cwd=ROOT, check=False).returncode:
        raise AssertionError("records.csv must remain unchanged")
    header = (ROOT / "records.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert_true("Nutrition Score" not in header, "CSV schema unchanged")
    print("PR10 Nutrition Intelligence validation passed")


if __name__ == "__main__":
    main()
