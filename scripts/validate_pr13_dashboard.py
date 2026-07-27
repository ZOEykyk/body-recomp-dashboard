from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyos_import import (  # noqa: E402
    canonical_to_projection,
    export_projection,
    normalize_import_document,
    preview_import,
    resolve_record_nutrition,
    workout_counts,
)
from dashboard_aggregation import aggregate_record, aggregate_records, project_dashboard_record  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    csv_path = ROOT / "records.csv"
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    workout = {
        "performed": True,
        "duration_minutes": 75,
        "exercises": [
            {"name": "Press", "sets": [{"weight_kg": 32, "reps": 10}, {"weight_kg": 32, "reps": 9}]},
        ],
    }
    row = {
        "日付": pd.Timestamp("2026-07-26"),
        "体重": 83.2,
        "睡眠時間": 8,
        "体調": 8,
        "歩数": 11786,
        "推定摂取カロリー": 2200,
        "タンパク質(g)": 145,
        "脂質(g)": 65,
        "炭水化物(g)": 248,
        "カロリー不明件数": 2,
        "筋トレ有無": "あり",
        "筋トレセッション数": 1,
        "筋トレ種目数": 1,
        "筋トレセット数": 2,
        "筋トレ時間(分)": 75,
        "構造化筋トレJSON": json.dumps(workout, ensure_ascii=False),
        "飲酒": "なし",
    }
    aggregate = aggregate_record(row)
    check(aggregate["weight_kg"] == 83.2, "dashboard weight equals stored value")
    check(aggregate["steps"] == 11786, "dashboard steps equal stored value")
    check(aggregate["calories_kcal"] == 2200, "dashboard calories equal stored value")
    check(aggregate["protein_g"] == 145, "dashboard protein equals stored value")
    check(aggregate["unknown_calorie_count"] == 2, "dashboard exposes unknown calorie count")
    check(aggregate["workout_session_count"] == 1, "dashboard session count equals stored value")
    check(aggregate["workout_exercise_count"] == 1, "dashboard exercise count equals stored value")
    check(aggregate["workout_set_count"] == 2, "dashboard set count equals stored value")

    missing = aggregate_record(
        {
            "体重": None,
            "睡眠時間": None,
            "体調": None,
            "歩数": None,
            "推定摂取カロリー": None,
            "筋トレ有無": "",
        }
    )
    check(missing["weight_kg"] is None, "missing weight is not zero")
    check(missing["calories_kcal"] is None, "missing calories remain unknown")
    check(not missing["workout_performed"], "missing workout is not performed")

    frame = aggregate_records(pd.DataFrame([row, {**row, "日付": pd.Timestamp("2026-07-27"), "歩数": 9000}]))
    check(frame["steps"].tolist() == [11786.0, 9000.0], "batch aggregate uses the same record contract")

    compatibility_fixture = json.loads(
        (ROOT / "tests/fixtures/pr13_compatibility_input_2026-07-26.json").read_text(encoding="utf-8")
    )
    compatibility_document = normalize_import_document(compatibility_fixture)
    compatibility_record = compatibility_document["records"][0]
    resolved_values = {
        "グリーンサラダ": 100,
        "チキンラーメン": 850,
        "卵": 80,
        "納豆": 90,
        "めかぶ": 20,
        "コーヒー": 20,
    }

    def deterministic_resolver(text: str, meal_type: str) -> dict:
        calories = resolved_values.get(text)
        if calories is None:
            return {"items": []}
        return {
            "items": [
                {
                    "selected_origin": "generic",
                    "total_nutrition": {"calories_kcal": calories, "basis": "total"},
                }
            ]
        }

    nutrition = resolve_record_nutrition(compatibility_record, deterministic_resolver)
    persisted = canonical_to_projection(compatibility_record, nutrition)
    persisted.update(
        {
            "間食": float("nan"),
            "間食カロリー(kcal)": 999,
            "仕事中のドリンク": float("nan"),
            "イベント名": float("nan"),
            "飲酒内容": float("nan"),
            "コメント": "['1週間ぶりのジム再開', '彼女と江戸川橋のnove.でランチ']",
            "Body Score": 87,
            "今日の採点": 0,
            "カロリー推定信頼度": "medium",
        }
    )
    dashboard = project_dashboard_record(persisted)
    check(preview_import(compatibility_document, set())["meal_item_count"] == 11, "preview retains eleven foods")
    check(dashboard["meal_item_count"] == 11, "dashboard projection retains eleven foods")
    check(
        dashboard["meals"]["snacks"]["display_text"] == "ドトール スイートポテト、コーヒー、ジェラート",
        "snack foods are projected from structured meals",
    )
    check(dashboard["meals"]["breakfast"]["calories_kcal"] == 298, "breakfast keeps at least 298 explicit kcal")
    check(
        dashboard["meals"]["lunch"]["calorie_display"] == "100kcal（既知分・不明1件）",
        "lunch shows its persisted known value as partial",
    )
    check(
        dashboard["meals"]["snacks"]["calorie_display"] == "150kcal（既知分・不明1件）",
        "snack calories show persisted known value and unknown item",
    )
    check(dashboard["known_meal_calories_kcal"] == 1588, "meal known totals sum to the stored daily total")
    check(dashboard["meal_calories_match_daily"], "meal and daily calories share one persisted source")
    check(
        dashboard["event_name"] == "—"
        and dashboard["alcohol_detail"] == "なし"
        and dashboard["meals"]["drinks"]["display_text"] == "なし",
        "missing display values never expose nan",
    )
    check(
        dashboard["notes"] == "1週間ぶりのジム再開 ／ 彼女と江戸川橋のnove.でランチ",
        "Python list notes render as natural text",
    )
    check(
        "間食: ドトール スイートポテト、コーヒー、ジェラート / 150kcal（既知分・不明1件）"
        in dashboard["recent_detail_lines"],
        "completed dashboard lines include all snack foods and persisted calories",
    )
    rendered_details = "\n".join(dashboard["recent_detail_lines"])
    check(
        not any(token in rendered_details for token in (": nan", ": NaN", ": None", ": []", "['")),
        "completed dashboard lines contain no raw null or Python list representation",
    )
    check(project_dashboard_record({**persisted, "コメント": "通常メモ"})["notes"] == "通常メモ", "string notes remain compatible")
    check(project_dashboard_record({**persisted, "コメント": []})["notes"] == "—", "empty notes are display-safe")
    exported = export_projection(persisted)
    check(
        sum(len(items) for items in exported["meals"].values()) == 11,
        "preview, persisted projection, dashboard, and export food counts agree",
    )
    check(workout_counts(exported["workout"]) == {"session_count": 1, "exercise_count": 6, "set_count": 20}, "workout projection stays intact")

    mutable_structured = json.loads(persisted["構造化食事JSON"])
    mutable_structured["lunch"]["totals"]["calories_kcal"] = 321
    changed_lunch = project_dashboard_record(
        {
            **persisted,
            "構造化食事JSON": json.dumps(mutable_structured, ensure_ascii=False),
            "昼カロリー(kcal)": 100,
        }
    )
    check(changed_lunch["meals"]["lunch"]["calories_kcal"] == 321, "lunch calories are not fixed to the legacy CSV value")

    user_visible = [
        meal["display_text"] for meal in dashboard["meals"].values()
    ] + [
        dashboard["event_name"],
        dashboard["alcohol_detail"],
        dashboard["notes"],
    ]
    forbidden = {"nan", "NaN", "None", "[]"}
    check(not any(value in forbidden or value.startswith("[") for value in user_visible), "UI projection hides raw null representations")

    after = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    check(before == after, "records.csv is unchanged")
    print("PR13 dashboard validation passed.")


if __name__ == "__main__":
    main()
