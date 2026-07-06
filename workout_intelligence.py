from __future__ import annotations

import re
from typing import Any

WORKOUT_INTELLIGENCE_VERSION = "1.0"


def get_nested_value(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def first_value(record: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = get_nested_value(record, key) if "." in key else record.get(key)
        if value is not None and value != "":
            return value
    return default


def normalize_workout_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " / ".join(normalize_workout_text(item) for item in value if item)
    if isinstance(value, dict):
        exercise = value.get("exercise") or value.get("種目") or value.get("name")
        result = value.get("result") or value.get("結果") or value.get("sets") or value.get("reps")
        if exercise or result:
            return " ".join(str(part).strip() for part in [exercise, result] if part)
        for key in ["menu", "detail", "details", "training_detail", "workout_detail", "筋トレ内容"]:
            if key in value:
                return normalize_workout_text(value[key])
    return str(value).strip()


def workout_text_from_record(record: dict[str, Any]) -> str:
    workout = record.get("workout") if isinstance(record.get("workout"), dict) else {}
    return normalize_workout_text(
        first_value(
            record,
            "筋トレ内容",
            "training_detail",
            "workout_detail",
            "menu",
            "workout.menu",
            "workout.detail",
            default=workout,
        )
    )


def split_exercise_entries(text: str) -> list[str]:
    normalized = str(text or "")
    lines = [line.strip(" \t-:：。") for line in re.split(r"[\n\r;；]+", normalized) if line.strip(" \t-:：。")]
    entries: list[str] = []
    for line in lines:
        parts = [part.strip() for part in re.split(r"\s*/\s*", line) if part.strip()]
        for part in parts:
            if entries and re.match(r"^\d", part):
                entries[-1] = f"{entries[-1]} / {part}"
            else:
                entries.append(part)
    return entries


def clean_exercise_name(entry: str) -> str:
    name = re.split(r"\d+(?:\.\d+)?\s*(?:kg|キロ|回|rep|reps)|×|x", entry, maxsplit=1, flags=re.IGNORECASE)[0]
    if name == entry:
        name = re.sub(r"\s+\d.*$", "", entry)
    name = re.sub(r"[()（）\[\]【】]", "", name).strip(" \t-:：")
    return name or "unknown"


def parse_reps_text(reps_text: str) -> list[int]:
    return [int(value) for value in re.findall(r"\d+", reps_text)]


def parse_reps_segment(segment: str) -> list[int]:
    reps_times_sets = re.search(r"(\d+)\s*(?:回|reps?)\s*[x×]\s*(\d+)", segment, flags=re.IGNORECASE)
    if reps_times_sets:
        return [int(reps_times_sets.group(1))] * int(reps_times_sets.group(2))

    repeated_set_match = re.search(r"[x×]\s*(\d+)\s*[x×]\s*(\d+)", segment, flags=re.IGNORECASE)
    if repeated_set_match:
        return [int(repeated_set_match.group(1))] * int(repeated_set_match.group(2))

    explicit_sets = re.search(r"(\d+)\s*(?:セット|sets?)", segment, flags=re.IGNORECASE)
    explicit_reps = re.search(r"(\d+)\s*(?:回|reps?)", segment, flags=re.IGNORECASE)
    if explicit_reps:
        reps = [int(explicit_reps.group(1))]
        if explicit_sets:
            reps = reps * int(explicit_sets.group(1))
        return reps

    return parse_reps_text(segment)


def parse_weighted_sets(entry: str) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(?:kg|キロ)", entry, flags=re.IGNORECASE))
    work_sets: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(entry)
        segment = entry[match.end() : end]
        reps = parse_reps_segment(segment)
        weight = float(match.group(1))
        work_sets.append(
            {
                "weight_kg": weight,
                "reps": reps,
                "sets": len(reps) if reps else None,
                "total_reps": sum(reps) if reps else None,
                "volume_kg": round(sum(rep * weight for rep in reps), 1) if reps else None,
            }
        )
    return work_sets


def parse_exercise_entry(entry: str) -> dict[str, Any]:
    exercise = clean_exercise_name(entry)
    work_sets = parse_weighted_sets(entry)
    if work_sets:
        top_set = max(work_sets, key=lambda item: item["weight_kg"])
        weight = top_set["weight_kg"]
        reps = top_set["reps"]
        sets = top_set["sets"]
    else:
        weight = None
        reps = parse_reps_segment(entry)
        sets = len(reps) if reps else None

    volume = sum(work_set.get("volume_kg") or 0 for work_set in work_sets) if work_sets else None
    estimated_1rm = None
    if weight is not None and reps:
        estimated_1rm = round(max(weight * (1 + rep / 30) for rep in reps), 1)

    return {
        "exercise": exercise,
        "raw": entry,
        "weight_kg": weight,
        "reps": reps,
        "sets": sets,
        "total_reps": sum(reps) if reps else None,
        "volume_kg": round(volume, 1) if volume is not None else None,
        "estimated_1rm_kg": estimated_1rm,
        "work_sets": work_sets,
        "bodyweight": weight is None and bool(reps),
        "confidence": "high" if weight is not None and reps else "medium" if exercise != "unknown" else "low",
    }


def parse_workout_detail(text: str) -> list[dict[str, Any]]:
    return [parse_exercise_entry(entry) for entry in split_exercise_entries(text)]


def best_history_by_exercise(history: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for record in history or []:
        for exercise in parse_workout_detail(workout_text_from_record(record)):
            name = exercise["exercise"]
            current = best.setdefault(name, {"max_weight_kg": 0, "max_volume_kg": 0, "max_estimated_1rm_kg": 0})
            current["max_weight_kg"] = max(current["max_weight_kg"], exercise.get("weight_kg") or 0)
            current["max_volume_kg"] = max(current["max_volume_kg"], exercise.get("volume_kg") or 0)
            current["max_estimated_1rm_kg"] = max(current["max_estimated_1rm_kg"], exercise.get("estimated_1rm_kg") or 0)
    return best


def weight_increment_for(exercise_name: str) -> float:
    text = exercise_name.lower()
    if "レッグプレス" in text:
        return 20.0
    if any(keyword in text for keyword in ["サイド", "カール", "レイズ", "dumbbell", "db"]):
        return 1.0
    return 2.5


def next_target_for(exercise: dict[str, Any], history_best: dict[str, Any] | None = None) -> dict[str, Any]:
    weight = exercise.get("weight_kg")
    reps = exercise.get("reps") or []
    if weight is None:
        return {"exercise": exercise["exercise"], "target": "重量と回数を記録する", "reason": "次回提案には重量と回数が必要です。"}

    min_reps = min(reps) if reps else 0
    max_reps = max(reps) if reps else 0
    increment = weight_increment_for(exercise["exercise"])
    exercise_name = exercise["exercise"]
    if "ベンチプレス" in exercise_name and len(reps) >= 4 and min_reps >= 5:
        return {
            "exercise": exercise_name,
            "target_weight_kg": weight + increment,
            "target_reps": [5] * min(4, len(reps)),
            "target": f"{weight + increment:g}kgで5回×4セットを狙う",
            "reason": "ベンチプレスで5回×4セット相当を達成しているため、小さく重量を上げます。",
        }
    if "レッグプレス" in exercise_name and reps and min_reps >= 15:
        return {
            "exercise": exercise_name,
            "target_weight_kg": weight + increment,
            "target_reps": reps,
            "target": f"{weight + increment:g}kgで同じセット構成を狙う",
            "reason": "レッグプレスで高レップが揃っているため、次の重量帯を狙います。",
        }
    if any(keyword in exercise_name for keyword in ["カール", "EZ"]) and reps and min_reps >= 12:
        return {
            "exercise": exercise_name,
            "target_weight_kg": weight + increment,
            "target_reps": reps,
            "target": f"{weight + increment:g}kgで同じセット構成を狙う",
            "reason": "カール種目で12回が揃っているため、増量候補です。",
        }

    next_reps = [rep + 1 for rep in reps] if reps else [5]
    if max_reps >= 10:
        next_reps = reps
    return {
        "exercise": exercise_name,
        "target_weight_kg": weight,
        "target_reps": next_reps,
        "target": f"{weight:g}kgを維持してフォームと総レップ安定を狙う",
        "reason": "増量前に同じ重量でセット全体を安定させます。",
    }


def detect_prs(exercises: list[dict[str, Any]], history_best: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    prs: list[dict[str, Any]] = []
    for exercise in exercises:
        best = history_best.get(exercise["exercise"], {})
        checks = [
            ("weight", "重量PR", exercise.get("weight_kg"), best.get("max_weight_kg", 0), "kg"),
            ("volume", "ボリュームPR", exercise.get("volume_kg"), best.get("max_volume_kg", 0), "kg"),
            ("estimated_1rm", "推定1RM PR", exercise.get("estimated_1rm_kg"), best.get("max_estimated_1rm_kg", 0), "kg"),
        ]
        for metric, label, current, previous, unit in checks:
            if current is not None and current > 0 and current > previous:
                prs.append(
                    {
                        "exercise": exercise["exercise"],
                        "metric": metric,
                        "label": label,
                        "value": current,
                        "previous_best": previous or None,
                        "unit": unit,
                    }
                )
    return prs


def analyze_workout(record: dict[str, Any], history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Analyze workout text without mutating the input record."""
    text = workout_text_from_record(record)
    exercises = parse_workout_detail(text)
    history_best = best_history_by_exercise(history)
    prs = detect_prs(exercises, history_best)
    next_targets = [next_target_for(exercise, history_best.get(exercise["exercise"])) for exercise in exercises]
    parsed_exercises = [exercise for exercise in exercises if exercise["confidence"] in {"high", "medium"}]
    performed = bool(text and parsed_exercises)

    if not text:
        summary = "筋トレ記録がありません。"
    elif not exercises:
        summary = "筋トレ内容を解析できませんでした。"
    elif prs:
        summary = f"{len(prs)}件のPR候補があります。"
    else:
        summary = f"{len(parsed_exercises)}種目を解析しました。"

    return {
        "metadata": {"workout_intelligence_version": WORKOUT_INTELLIGENCE_VERSION},
        "performed": performed,
        "summary": summary,
        "raw_text": text,
        "exercise_count": len(parsed_exercises),
        "exercises": exercises,
        "prs": prs,
        "next_targets": next_targets,
        "progression": {"history_exercises": history_best},
        "coach": {
            "message": summary,
            "next_focus": next_targets[0]["target"] if next_targets else "",
        },
        "confidence": "high" if exercises and all(item["confidence"] == "high" for item in exercises) else "medium" if exercises else "low",
    }
