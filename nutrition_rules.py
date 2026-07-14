"""Central Japanese templates and deterministic recommendation precedence."""
from __future__ import annotations

from typing import Any


NUTRITION_RULESET_VERSION = "1.0"
VEGETABLE_KEYWORDS = ("サラダ", "野菜", "温野菜", "海藻", "めかぶ", "わかめ", "きのこ", "舞茸", "ほうれん草", "ブロッコリー", "具だくさん")
TOMATO_JUICE_KEYWORDS = ("理想のトマト", "トマトジュース")
SUPPORTIVE_SNACK_KEYWORDS = ("オイコス", "oikos", "savas", "ザバス", "プロテイン", "サラダチキン", "ゆで卵")
DISCRETIONARY_SNACK_KEYWORDS = ("アイス", "チョコ", "ポテトチップ", "スナック菓子", "ドーナツ", "ケーキ", "フライド")


def priority_item(code: str, severity: str, title: str, detail: str, *, actual: Any = None, target: Any = None, difference: Any = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "title": title, "detail": detail, "actual": actual, "target": target, "difference": difference}


def strength_item(code: str, title: str, detail: str) -> dict[str, str]:
    return {"code": code, "title": title, "detail": detail}


def action_for_priority(priority: dict[str, Any], status: str) -> dict[str, str]:
    code = priority["code"]
    future = "明日は" if status == "complete_day" else "次の食事は"
    templates = {
        "data_quality_low": ("商品名かラベル情報を補足する", "正確な商品名または栄養ラベルを追加すると、評価精度が上がります。"),
        "calories_high": (f"{future}追加の高カロリー品を控える", "主食量か揚げ物を一つだけ減らし、追加の間食は控えてください。"),
        "calories_low": (f"{future}主食とタンパク質を補う", "ご飯・パンなどの主食に、卵・魚・鶏肉・大豆製品を組み合わせてください。"),
        "protein_low": (f"{future}タンパク質を一品追加する", "魚、鶏むね、卵、豆腐、プロテインのいずれかを追加してください。"),
        "fat_high": (f"{future}脂質を抑える", "魚、鶏むね、豆腐を中心にし、揚げ物やマヨネーズを控えてください。"),
        "vegetables_low": (f"{future}野菜か海藻を一品追加する", "サラダ、海藻、温野菜、きのこのいずれかを追加してください。"),
        "fiber_low": (f"{future}食物繊維源を足す", "野菜、海藻、きのこ、豆類を一品追加してください。"),
        "salt_high": (f"{future}汁物を一回までにする", "汁を残すか、加工食品と濃い味の組み合わせを避けてください。"),
        "snack_high": ("間食を一回分減らす", "甘い間食は一品までにし、必要なら高タンパクな選択へ置き換えてください。"),
    }
    title, detail = templates.get(code, (priority["title"], priority["detail"]))
    return {"title": title, "detail": detail}


def severity_rank(value: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(value, 3)
