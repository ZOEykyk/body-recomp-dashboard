"""Deterministic, UI-independent Nutrition Intelligence Engine v1."""
from __future__ import annotations

from copy import deepcopy
import datetime as dt
from typing import Any

from food_resolver import resolve_food_text
from nutrition_intelligence_models import (
    METRIC_FIELDS,
    NUTRITION_INTELLIGENCE_VERSION,
    NUTRITION_RULESET_VERSION,
    SCORE_WEIGHTS,
    as_positive_number,
    meal_texts,
    numeric_nutrition_from_record,
    record_value,
)
from nutrition_rules import (
    DISCRETIONARY_SNACK_KEYWORDS,
    NUTRITION_RULESET_VERSION as RULESET_VERSION,
    SUPPORTIVE_SNACK_KEYWORDS,
    TOMATO_JUICE_KEYWORDS,
    VEGETABLE_KEYWORDS,
    action_for_priority,
    priority_item,
    severity_rank,
    strength_item,
)
from nutrition_targets import NUTRITION_TARGET_VERSION, calculate_nutrition_targets


SOURCE_CONFIDENCE = {
    "explicit_user_label": 1.0,
    "official_product_page": 0.95,
    "official_nutrition_table": 0.95,
    "official_api_or_catalog": 0.9,
    "bodyos_verified": 0.85,
    "user_verified": 0.72,
    "general_reference": 0.62,
    "legacy_dictionary": 0.5,
    "fallback_estimate": 0.25,
}
MEAL_CALORIE_COLUMNS = {
    "breakfast": "朝カロリー(kcal)",
    "lunch": "昼カロリー(kcal)",
    "dinner": "夜カロリー(kcal)",
    "snacks": "間食カロリー(kcal)",
    "work_drinks": "ドリンクカロリー(kcal)",
}


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _is_no_meal(text: str) -> bool:
    return text.strip().lower() in {"なし", "無し", "食べていない", "食べてない", "未食", "抜き", "スキップ", "食事なし"}


def determine_day_status(record: dict[str, Any], now: dt.datetime | None = None) -> tuple[str, float]:
    explicit = record_value(record, "day_completion_state", "completion_state", "日次完了状態")
    if explicit in {"morning_only", "partial_day", "complete_day", "unknown_completion"}:
        return str(explicit), {"morning_only": 0.25, "partial_day": 0.60, "complete_day": 1.0, "unknown_completion": 0.5}[str(explicit)]
    meals = meal_texts(record)
    entered = {name for name in ("breakfast", "lunch", "dinner") if meals[name] and not _is_no_meal(meals[name])}
    current_day = _date(record_value(record, "date", "日付")) == (now or dt.datetime.now()).date()
    if not entered:
        return "unknown_completion", 0.5
    if entered == {"breakfast"}:
        return "morning_only", 0.25
    if "dinner" in entered:
        return "complete_day", 1.0
    if not current_day:
        return "complete_day", 1.0
    return "partial_day", 0.60


def _aggregate_from_meals(
    record: dict[str, Any],
    food_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate only known nutrition fields; unknown macro values remain None."""
    direct = numeric_nutrition_from_record(record)
    totals: dict[str, float | None] = {field: direct.get(field) for field in METRIC_FIELDS}
    sources: dict[str, int] = {}
    origins: dict[str, int] = {}
    known_items = estimated_items = unresolved_items = 0
    meal_totals: dict[str, dict[str, Any]] = {}
    meals = meal_texts(record)
    inferred: dict[str, float] = {field: 0.0 for field in METRIC_FIELDS if field != "hydration_ml"}
    field_complete: dict[str, bool] = {field: True for field in inferred}
    any_item = False

    for meal_type, text in meals.items():
        meal_totals[meal_type] = {"calories_kcal": as_positive_number(record.get(MEAL_CALORIE_COLUMNS.get(meal_type, ""))), "items": 0}
        if not text or _is_no_meal(text):
            continue
        resolution = resolve_food_text(text, meal_type, knowledge=food_knowledge)
        resolved_items = resolution.get("items") or []
        meal_totals[meal_type]["items"] = len(resolved_items)
        if resolution.get("meal_explicit"):
            any_item = True
            known_items += max(len(resolved_items), 1)
            sources["explicit_user_label"] = sources.get("explicit_user_label", 0) + max(len(resolved_items), 1)
            origins["explicit"] = origins.get("explicit", 0) + max(len(resolved_items), 1)
            nutrition = resolution.get("total_nutrition") or {}
            for field in inferred:
                value = as_positive_number(nutrition.get(field))
                if value is None:
                    field_complete[field] = False
                else:
                    inferred[field] += value
            meal_totals[meal_type]["calories_kcal"] = as_positive_number(nutrition.get("calories_kcal"))
            continue

        for resolved in resolved_items:
            any_item = True
            selected = resolved.get("selected") or {}
            origin = str(resolved.get("selected_origin") or "fallback")
            source_type = str((selected.get("source") or {}).get("source_type") or "fallback_estimate")
            origins[origin] = origins.get(origin, 0) + 1
            sources[source_type] = sources.get(source_type, 0) + 1
            nutrition = resolved.get("total_nutrition") or {}
            if origin == "fallback" or as_positive_number(nutrition.get("calories_kcal")) is None:
                unresolved_items += 1
                estimated_items += 1
                for field in field_complete:
                    field_complete[field] = False
                continue
            known_items += 1
            if origin == "generic":
                estimated_items += 1
                if resolved.get("item", {}).get("needs_review"):
                    unresolved_items += 1
            for field in inferred:
                value = as_positive_number(nutrition.get(field))
                if value is None:
                    field_complete[field] = False
                else:
                    inferred[field] += value
        resolved_calories = as_positive_number((resolution.get("total_nutrition") or {}).get("calories_kcal"))
        if resolved_calories is not None:
            meal_totals[meal_type]["calories_kcal"] = resolved_calories

    if totals["calories_kcal"] is None:
        meal_column_values = [as_positive_number(record.get(column)) for column in MEAL_CALORIE_COLUMNS.values()]
        if any(value is not None for value in meal_column_values):
            totals["calories_kcal"] = sum(value or 0.0 for value in meal_column_values)
            sources["legacy_dictionary"] = sources.get("legacy_dictionary", 0) + 1
        elif any_item and field_complete["calories_kcal"]:
            totals["calories_kcal"] = inferred["calories_kcal"]
    for field in ("protein_g", "fat_g", "carbs_g", "fiber_g", "salt_g"):
        if totals[field] is None and any_item and field_complete[field]:
            totals[field] = inferred[field]

    vegetables = _vegetable_evidence(meals)
    snacks = _snack_analysis(meals.get("snacks", ""), meal_totals.get("snacks", {}).get("calories_kcal"), totals["calories_kcal"])
    return {
        "totals": totals,
        "meal_totals": meal_totals,
        "known_item_count": known_items,
        "estimated_item_count": estimated_items,
        "unresolved_item_count": unresolved_items,
        "source_type_distribution": sources,
        "resolution_origin_distribution": origins,
        "vegetables": vegetables,
        "snacks": snacks,
        "has_meal_text": any(bool(text) for text in meals.values()),
        "alcohol": _alcohol_context(record),
    }


def _vegetable_evidence(meals: dict[str, str]) -> dict[str, Any]:
    evidence: list[str] = []
    servings = 0.0
    for text in meals.values():
        normalized = text.lower()
        for keyword in VEGETABLE_KEYWORDS:
            if keyword in normalized:
                evidence.append(keyword)
                servings += 1.0
        if any(keyword in normalized for keyword in TOMATO_JUICE_KEYWORDS):
            evidence.append("tomato_juice")
            servings += 0.25
    return {"estimated_servings": min(servings, 3.0), "confidence": "low", "evidence_fragments": evidence}


def _snack_analysis(text: str, snack_calories: float | None, total_calories: float | None) -> dict[str, Any]:
    normalized = text.lower()
    supportive = any(keyword in normalized for keyword in SUPPORTIVE_SNACK_KEYWORDS)
    discretionary = any(keyword in normalized for keyword in DISCRETIONARY_SNACK_KEYWORDS)
    return {
        "calories_kcal": snack_calories,
        "percentage_of_total": round(snack_calories / total_calories * 100, 1) if snack_calories and total_calories else None,
        "supportive": supportive,
        "discretionary": discretionary,
    }


def _alcohol_context(record: dict[str, Any]) -> dict[str, Any]:
    status = str(record_value(record, "飲酒", "alcohol") or "").strip().lower()
    detail = str(record_value(record, "飲酒内容", "alcohol_detail") or "").strip()
    recorded = status in {"あり", "true", "yes", "1"}
    return {"recorded": recorded, "detail_present": bool(detail), "ambiguous": bool(detail) and not recorded}


def _component(name: str, actual: float | None, target: Any, points: int, status: str, explanation: str, available: bool, trace: list[dict[str, Any]]) -> dict[str, Any]:
    earned = 0.0 if not available else {"excellent": points, "good": points * 0.9, "watch": points * 0.6, "poor": points * 0.25}.get(status, 0.0)
    trace.append({"rule_code": f"{name}_{status}", "component": name, "inputs": {"actual": actual, "target": target}, "result": status, "points": round(earned, 1)})
    return {"actual": actual, "target": target, "points": round(earned, 1), "max_points": points, "status": status, "explanation": explanation, "available": available}


def _score_components(aggregation: dict[str, Any], targets: dict[str, Any], status: str, progress: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    totals = aggregation["totals"]
    trace: list[dict[str, Any]] = []
    complete = status == "complete_day"
    components: dict[str, Any] = {}
    calorie_target = targets["calorie_target"] * (1 if complete else progress)
    calories = totals["calories_kcal"]
    if calories is None:
        components["calories"] = _component("calories", None, calorie_target, 20, "unavailable", "カロリー記録がありません。", False, trace)
    else:
        ratio = calories / calorie_target
        state = "excellent" if 0.85 <= ratio <= 1.10 else "good" if 0.70 <= ratio <= 1.25 else "watch" if 0.55 <= ratio <= 1.40 else "poor"
        components["calories"] = _component("calories", calories, round(calorie_target), 20, state, "進捗に合わせたカロリー目標と比較しています。", True, trace)
    protein_target = targets["protein_target_g"] * (1 if complete else progress)
    protein = totals["protein_g"]
    if protein is None:
        components["protein"] = _component("protein", None, protein_target, 20, "unavailable", "タンパク質の実測値が不足しています。", False, trace)
    else:
        ratio = protein / protein_target
        state = "excellent" if ratio >= 1 else "good" if ratio >= .8 else "watch" if ratio >= .55 else "poor"
        components["protein"] = _component("protein", protein, round(protein_target, 1), 20, state, "進捗に合わせたタンパク質目標と比較しています。", True, trace)
    for name, field, min_key, max_key, points in (("fat", "fat_g", "fat_target_min_g", "fat_target_max_g", 15), ("carbs", "carbs_g", "carbs_target_min_g", "carbs_target_max_g", 10)):
        actual = totals[field]
        low, high = targets[min_key] * (1 if complete else progress), targets[max_key] * (1 if complete else progress)
        if actual is None:
            components[name] = _component(name, None, {"min": round(low, 1), "max": round(high, 1)}, points, "unavailable", "栄養成分の実測値が不足しています。", False, trace)
        else:
            state = "excellent" if low <= actual <= high else "good" if low * .8 <= actual <= high * 1.12 else "watch" if low * .6 <= actual <= high * 1.25 else "poor"
            components[name] = _component(name, actual, {"min": round(low, 1), "max": round(high, 1)}, points, state, "進捗に合わせた範囲と比較しています。", True, trace)
    for name, field, target, points, upper in (("fiber", "fiber_g", targets["fiber_target_g"] * (1 if complete else progress), 10, False), ("salt", "salt_g", targets["salt_limit_g"] * (1 if complete else progress), 10, True), ("hydration", "hydration_ml", targets["hydration_target_ml"] * (1 if complete else progress), 5, False)):
        actual = totals[field]
        if actual is None:
            components[name] = _component(name, None, round(target, 1), points, "unavailable", "記録がないため評価しません。", False, trace)
        else:
            ratio = actual / target
            state = ("excellent" if ratio <= 1 else "good" if ratio <= 1.12 else "watch" if ratio <= 1.3 else "poor") if upper else ("excellent" if ratio >= 1 else "good" if ratio >= .8 else "watch" if ratio >= .55 else "poor")
            components[name] = _component(name, actual, round(target, 1), points, state, "進捗に合わせた目標と比較しています。", True, trace)
    vegetables = aggregation["vegetables"]["estimated_servings"]
    vegetable_target = targets["vegetable_target_servings"] * (1 if complete else progress)
    vegetable_state = "excellent" if vegetables >= vegetable_target else "good" if vegetables >= vegetable_target * .8 else "watch" if vegetables >= vegetable_target * .4 else "poor"
    components["vegetables"] = _component("vegetables", vegetables if aggregation["has_meal_text"] else None, round(vegetable_target, 1), 10, vegetable_state if aggregation["has_meal_text"] else "unavailable", "食事テキストの野菜・海藻・きのこ表現から控えめに推定しています。", aggregation["has_meal_text"], trace)
    return components, trace


def _confidence(aggregation: dict[str, Any], components: dict[str, Any], status: str) -> dict[str, Any]:
    sources = aggregation["source_type_distribution"]
    known = aggregation["known_item_count"]
    estimated = aggregation["estimated_item_count"]
    unresolved = aggregation["unresolved_item_count"]
    total_items = known + estimated
    known_ratio = known / total_items if total_items else (1.0 if aggregation["totals"]["calories_kcal"] is not None else 0.0)
    fallback_ratio = estimated / total_items if total_items else 0.0
    macro_components = [components[key] for key in ("protein", "fat", "carbs", "fiber", "salt")]
    macro_coverage = sum(component["available"] for component in macro_components) / len(macro_components)
    source_quality = sum(SOURCE_CONFIDENCE.get(source, .25) * count for source, count in sources.items()) / max(sum(sources.values()), 1)
    score = max(0.05, min(1.0, .40 * known_ratio + .30 * macro_coverage + .30 * source_quality - min(.15, unresolved * .05)))
    level = "high" if score >= .80 else "medium" if score >= .55 else "low"
    reasons: list[str] = []
    if unresolved: reasons.append(f"未確認食品 {unresolved}件")
    if macro_coverage < .6: reasons.append("PFC等の栄養成分が一部不足")
    if fallback_ratio >= .3: reasons.append("推定値の割合が高い")
    if aggregation["alcohol"]["ambiguous"]: reasons.append("飲酒カロリーの内訳が曖昧")
    if status in {"morning_only", "unknown_completion"}: reasons.append("一日の記録が未完了")
    return {"score": round(score, 2), "level": level, "known_calorie_ratio": round(known_ratio, 2), "macro_coverage": round(macro_coverage, 2), "fallback_ratio": round(fallback_ratio, 2), "unresolved_count": unresolved, "reasons": reasons}


def _insights(components: dict[str, Any], aggregation: dict[str, Any], status: str, confidence: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    strengths: list[dict[str, Any]] = []
    priorities: list[dict[str, Any]] = []
    protein = components["protein"]
    if protein["available"] and protein["status"] in {"excellent", "good"}:
        wording = "達成しています" if status == "complete_day" and protein["status"] == "excellent" else "順調です"
        strengths.append(strength_item("protein_on_track", "タンパク質は順調", f"現在 {protein['actual']:.0f}gで、目標進捗 {protein['target']:.0f}gに対して{wording}。"))
    for name, title in (("calories", "カロリーは目標範囲"), ("fat", "脂質はバランス内"), ("vegetables", "野菜の記録あり")):
        component = components[name]
        if component["available"] and component["status"] == "excellent" and len(strengths) < 3:
            strengths.append(strength_item(f"{name}_on_track", title, component["explanation"]))
    calories = components["calories"]
    if calories["available"] and calories["status"] in {"watch", "poor"}:
        code = "calories_high" if calories["actual"] > calories["target"] else "calories_low"
        severity = "high" if calories["status"] == "poor" else "medium"
        priorities.append(priority_item(code, severity, "カロリーが目標進捗から外れ気味", "一日の進捗を踏まえ、次の食事で量を調整してください。", actual=calories["actual"], target=calories["target"], difference=round(calories["actual"] - calories["target"], 1)))
    if protein["available"] and protein["status"] in {"watch", "poor"}:
        priorities.append(priority_item("protein_low", "high" if protein["status"] == "poor" else "medium", "タンパク質が不足気味", "次の食事でタンパク質源を追加してください。", actual=protein["actual"], target=protein["target"], difference=round(protein["target"] - protein["actual"], 1)))
    fat = components["fat"]
    if fat["available"] and fat["actual"] > fat["target"]["max"]:
        priorities.append(priority_item("fat_high", "high" if fat["status"] == "poor" else "medium", "脂質が多め", "次の食事は揚げ物・高脂質な追加を控えると整います。", actual=fat["actual"], target=fat["target"]["max"], difference=round(fat["actual"] - fat["target"]["max"], 1)))
    vegetables = components["vegetables"]
    if vegetables["status"] in {"watch", "poor"}:
        priorities.append(priority_item("vegetables_low", "medium", "野菜・海藻が少なめ", "トマトジュースだけでは十分量とみなさず、野菜・海藻・きのこを追加してください。", actual=vegetables["actual"], target=vegetables["target"], difference=round(vegetables["target"] - vegetables["actual"], 1)))
    for name, code, title in (("fiber", "fiber_low", "食物繊維が不足気味"), ("salt", "salt_high", "塩分が多め")):
        component = components[name]
        if component["available"] and component["status"] in {"watch", "poor"}:
            priorities.append(priority_item(code, "medium", title, component["explanation"], actual=component["actual"], target=component["target"]))
    snack = aggregation["snacks"]
    if snack["calories_kcal"] and snack["percentage_of_total"] and snack["percentage_of_total"] >= 25 and snack["discretionary"] and not snack["supportive"]:
        priorities.append(priority_item("snack_high", "medium", "間食カロリーが多め", "間食が総カロリーに占める割合が高めです。", actual=snack["calories_kcal"], target=None))
    if confidence["level"] == "low":
        priorities.append(priority_item("data_quality_low", "low", "栄養データの確度が低め", "未確認食品やPFC不足があるため、評価は参考値です。"))
    if aggregation["alcohol"]["recorded"]:
        priorities.append(priority_item("alcohol_recorded", "low", "飲酒を記録", "飲酒カロリーの内訳は現在の入力では正確に分けられないため、総量は参考値です。"))
    priorities.sort(key=lambda item: (severity_rank(item["severity"]), item["code"]))
    actions: list[dict[str, Any]] = []
    for priority in priorities:
        action = action_for_priority(priority, status)
        if action["title"] not in {item["title"] for item in actions}:
            actions.append({"priority": len(actions) + 1, **action, "rule_code": priority["code"]})
        if len(actions) == 3:
            break
    return strengths[:3], priorities[:3], actions


def _comparison(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {"available": False}
    fields = ("calories_kcal", "protein_g", "fat_g", "carbs_g")
    result: dict[str, Any] = {"available": True, "score": {"current": current["score"], "previous": previous["score"], "difference": current["score"] - previous["score"], "direction": "up" if current["score"] > previous["score"] else "down" if current["score"] < previous["score"] else "flat"}, "confidence": {"current": current["confidence"]["score"], "previous": previous["confidence"]["score"], "difference": round(current["confidence"]["score"] - previous["confidence"]["score"], 2)}}
    for field in fields:
        now_value, prior_value = current["totals"].get(field), previous["totals"].get(field)
        if now_value is not None and prior_value is not None:
            difference = round(now_value - prior_value, 1)
            result[field] = {"current": now_value, "previous": prior_value, "difference": difference, "direction": "up" if difference > 0 else "down" if difference < 0 else "flat"}
    return result


def _seven_day(history_results: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [item for item in history_results if item["status"] == "complete_day" and item["totals"].get("calories_kcal") is not None][-7:]
    if len(valid) < 2:
        return {"available": False, "valid_day_count": len(valid), "reason": "at_least_two_complete_days_required"}
    def average(field: str) -> float | None:
        values = [item["totals"].get(field) for item in valid if item["totals"].get(field) is not None]
        return round(sum(values) / len(values), 1) if values else None
    return {"available": True, "valid_day_count": len(valid), "average_score": round(sum(item["score"] for item in valid) / len(valid), 1), "average_calories_kcal": average("calories_kcal"), "average_protein_g": average("protein_g"), "average_fat_g": average("fat_g"), "average_carbs_g": average("carbs_g"), "trend_confidence": "strong" if len(valid) >= 4 else "limited"}


def analyze_nutrition(
    record: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
    food_knowledge: dict[str, Any] | None = None,
    _with_comparisons: bool = True,
) -> dict[str, Any]:
    """Analyze one record without mutation, IO, Streamlit, network, or an LLM."""
    safe_record, safe_history, safe_profile = deepcopy(record or {}), deepcopy(history or []), deepcopy(profile or {})
    safe_food_knowledge = deepcopy(food_knowledge) if isinstance(food_knowledge, dict) else None
    status, progress = determine_day_status(safe_record, now)
    targets = calculate_nutrition_targets(safe_profile)
    aggregation = _aggregate_from_meals(safe_record, safe_food_knowledge)
    components, rule_trace = _score_components(aggregation, targets, status, progress)
    available_points = sum(component["max_points"] for component in components.values() if component["available"])
    earned_points = sum(component["points"] for component in components.values() if component["available"])
    score = round(earned_points / available_points * 100) if available_points else 0
    confidence = _confidence(aggregation, components, status)
    strengths, priorities, actions = _insights(components, aggregation, status, confidence)
    if confidence["level"] == "low":
        summary = "未確認食品や栄養成分の不足があるため、栄養評価は参考値です。"
    elif status == "morning_only":
        summary = "朝食時点の記録です。最終評価ではなく、次の食事に向けた目安として表示しています。"
    elif status == "partial_day":
        summary = "現時点の記録範囲で評価しています。夕食までの選択でバランスを整えられます。"
    elif strengths:
        summary = strengths[0]["detail"]
    else:
        summary = "記録された栄養データをもとに、一日のバランスを評価しています。"
    result = {
        "engine_version": NUTRITION_INTELLIGENCE_VERSION,
        "ruleset_version": NUTRITION_RULESET_VERSION,
        "target_version": NUTRITION_TARGET_VERSION,
        "status": status,
        "expected_progress_ratio": progress,
        "score": score,
        "earned_points": round(earned_points, 1),
        "available_points": available_points,
        "confidence": confidence,
        "summary": summary,
        "totals": aggregation["totals"],
        "meal_totals": aggregation["meal_totals"],
        "targets": targets,
        "score_breakdown": components,
        "strengths": strengths,
        "priorities": priorities,
        "actions": actions,
        "comparisons": {"previous_day": {"available": False}, "seven_day": {"available": False}},
        "data_quality": {"known_item_count": aggregation["known_item_count"], "estimated_item_count": aggregation["estimated_item_count"], "unresolved_item_count": aggregation["unresolved_item_count"], "source_type_distribution": aggregation["source_type_distribution"], "resolution_origin_distribution": aggregation["resolution_origin_distribution"], "macro_coverage": confidence["macro_coverage"]},
        "vegetables": aggregation["vegetables"],
        "snacks": aggregation["snacks"],
        "alcohol": aggregation["alcohol"],
        "rule_trace": rule_trace,
    }
    if _with_comparisons:
        current_date = _date(record_value(safe_record, "date", "日付"))
        dated = [(item, _date(record_value(item, "date", "日付"))) for item in safe_history]
        prior = [item for item, date in dated if date and (current_date is None or date < current_date)]
        prior.sort(key=lambda item: _date(record_value(item, "date", "日付")) or dt.date.min)
        prior_results = [
            analyze_nutrition(
                item,
                history=None,
                profile=safe_profile,
                now=now,
                food_knowledge=safe_food_knowledge,
                _with_comparisons=False,
            )
            for item in prior
        ]
        result["comparisons"] = {"previous_day": _comparison(result, prior_results[-1] if prior_results else None), "seven_day": _seven_day(prior_results)}
    return result


__all__ = ["analyze_nutrition", "determine_day_status"]
