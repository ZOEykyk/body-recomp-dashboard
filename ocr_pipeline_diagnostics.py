from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from nutrition_label_parser import NUMBER_TOKEN


OCR_PIPELINE_DIAGNOSTICS_VERSION = "1.0"
CORE_FIELDS = ("calories_kcal", "protein_g", "fat_g", "carbs_g")
FIELD_KEYWORDS = {
    "calories_kcal": r"(?:熱量|エネルギー|カロリー|(?<![A-Za-z])(?:energy|calories?|kcal|kJ)(?![A-Za-z]))",
    "protein_g": r"(?:たんぱく質|タンパク質|蛋白質|(?<![A-Za-z])protein(?![A-Za-z])|(?<![A-Za-z])P(?=\s*[:：0-9]))",
    "fat_g": r"(?:脂質|(?<![A-Za-z])fat(?![A-Za-z])|(?<![A-Za-z])F(?=\s*[:：0-9]))",
    "carbs_g": r"(?:炭水化物|(?<![A-Za-z])(?:carbohydrates?|carbs?)(?![A-Za-z])|(?<![A-Za-z])C(?=\s*[:：0-9]))",
}
AMBIGUOUS_WARNING_CODES = {
    "basis_conflict",
    "multiple_nutrition_blocks",
    "multiple_values",
}


def _keyword_detection(text: str) -> dict[str, bool]:
    return {
        "calories": bool(re.search(FIELD_KEYWORDS["calories_kcal"], text, flags=re.IGNORECASE)),
        "protein": bool(re.search(FIELD_KEYWORDS["protein_g"], text, flags=re.IGNORECASE)),
        "fat": bool(re.search(FIELD_KEYWORDS["fat_g"], text, flags=re.IGNORECASE)),
        "carbs": bool(re.search(FIELD_KEYWORDS["carbs_g"], text, flags=re.IGNORECASE)),
    }


def _field_value_candidate_detection(text: str) -> dict[str, bool]:
    patterns = {
        "calories_kcal": rf"{FIELD_KEYWORDS['calories_kcal']}[^\n]{{0,32}}?{NUMBER_TOKEN}\s*(?:kcal|kJ)",
        "protein_g": rf"{FIELD_KEYWORDS['protein_g']}[^\n]{{0,32}}?{NUMBER_TOKEN}\s*g",
        "fat_g": rf"{FIELD_KEYWORDS['fat_g']}[^\n]{{0,32}}?{NUMBER_TOKEN}\s*g",
        "carbs_g": rf"{FIELD_KEYWORDS['carbs_g']}[^\n]{{0,32}}?{NUMBER_TOKEN}\s*g",
    }
    return {
        field: bool(re.search(pattern, text, flags=re.IGNORECASE))
        for field, pattern in patterns.items()
    }


def _field_reason_codes(
    field: str,
    evidence: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> list[str]:
    reasons = {
        str(item.get("code"))
        for item in warnings
        if item.get("field") == field and item.get("code")
    }
    statuses = {str(item.get("status")) for item in evidence if item.get("status")}
    if "ambiguous" in statuses:
        reasons.add("ambiguous_evidence")
    if "rejected" in statuses:
        reasons.add("rejected_evidence")
    if not evidence:
        reasons.add("not_detected")
    return sorted(reasons)


def _classification(
    *,
    token_count: int,
    field_value_candidates: dict[str, bool],
    selected_fields: list[str],
    rejected_fields: list[dict[str, Any]],
    basis: str,
    ambiguous: bool,
) -> dict[str, Any]:
    selected_core = {field for field in selected_fields if field in CORE_FIELDS}
    missing_core = set(CORE_FIELDS) - selected_core
    if ambiguous and (selected_core or rejected_fields):
        return {
            "code": "C",
            "stage": "handoff_ambiguity",
            "reason": "Parser found ambiguous evidence that requires Editor review.",
        }
    if not selected_core:
        has_mappable_signal = any(field_value_candidates.values())
        if token_count == 0 or not has_mappable_signal:
            return {
                "code": "A",
                "stage": "ocr_recognition",
                "reason": "OCR did not expose enough nutrition keywords or numeric candidates.",
            }
        return {
            "code": "B",
            "stage": "parser_mapping",
            "reason": "OCR exposed nutrition signals, but the Parser did not select a core field.",
        }
    if missing_core:
        if any(field_value_candidates[field] for field in missing_core):
            return {
                "code": "B",
                "stage": "parser_mapping",
                "reason": "OCR exposed a missing field, but the Parser did not select it.",
            }
        return {
            "code": "A",
            "stage": "ocr_recognition",
            "reason": "Some expected nutrition labels were not recognized by OCR.",
        }
    if basis == "unknown":
        return {
            "code": "C",
            "stage": "handoff_ambiguity",
            "reason": "Parser selected all core fields, but nutrition basis still requires Editor review.",
        }
    return {
        "code": None,
        "stage": "complete",
        "reason": "OCR and Parser selected all core fields with an explicit, unambiguous basis.",
    }


def build_ocr_pipeline_diagnostics(
    raw_text: str,
    parsed: dict[str, Any],
    *,
    token_count: int | None,
    average_confidence: float | None,
    median_confidence: float | None,
) -> dict[str, Any]:
    """Build payload-free diagnostics for one OCR-to-Parser execution."""
    text = str(raw_text or "")
    nutrition = parsed.get("nutrition") if isinstance(parsed.get("nutrition"), dict) else {}
    evidence_map = parsed.get("field_evidence") if isinstance(parsed.get("field_evidence"), dict) else {}
    warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
    keywords = _keyword_detection(text)
    field_value_candidates = _field_value_candidate_detection(text)
    kcal_candidate_count = len(re.findall(rf"{NUMBER_TOKEN}\s*kcal", text, flags=re.IGNORECASE))
    gram_candidate_count = len(re.findall(rf"{NUMBER_TOKEN}\s*g(?:\b|(?=[^A-Za-z]))", text, flags=re.IGNORECASE))

    selected_fields: list[str] = []
    rejected_fields: list[dict[str, Any]] = []
    for field in (*CORE_FIELDS, "basis"):
        evidence = evidence_map.get(field) if isinstance(evidence_map.get(field), list) else []
        selected = (
            nutrition.get(field) not in (None, "unknown")
            and any(item.get("status") in {"selected", "derived"} for item in evidence)
        )
        if selected:
            selected_fields.append(field)
            continue
        reasons = _field_reason_codes(field, evidence, warnings)
        if reasons:
            rejected_fields.append({"field": field, "reason_codes": reasons})

    ambiguous = any(str(item.get("code")) in AMBIGUOUS_WARNING_CODES for item in warnings)
    if not ambiguous:
        ambiguous = any(
            item.get("status") == "ambiguous"
            for entries in evidence_map.values()
            if isinstance(entries, list)
            for item in entries
            if isinstance(item, dict)
        )
    basis = str(nutrition.get("basis") or "unknown")
    classification = _classification(
        token_count=max(0, int(token_count or 0)),
        field_value_candidates=field_value_candidates,
        selected_fields=selected_fields,
        rejected_fields=rejected_fields,
        basis=basis,
        ambiguous=ambiguous,
    )
    return {
        "diagnostics_version": OCR_PIPELINE_DIAGNOSTICS_VERSION,
        "ocr": {
            "token_count": max(0, int(token_count or 0)),
            "average_confidence": average_confidence,
            "median_confidence": median_confidence,
        },
        "recognition": {
            "keyword_detected": deepcopy(keywords),
            "field_value_candidate_detected": deepcopy(field_value_candidates),
            "kcal_numeric_candidate_count": kcal_candidate_count,
            "gram_numeric_candidate_count": gram_candidate_count,
        },
        "parser": {
            "selected_fields": selected_fields,
            "rejected_fields": rejected_fields,
            "basis_candidate": basis,
            "ambiguous": ambiguous,
        },
        "classification": classification,
    }


__all__ = [
    "OCR_PIPELINE_DIAGNOSTICS_VERSION",
    "build_ocr_pipeline_diagnostics",
]
