from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
import unicodedata


NUTRITION_LABEL_PARSER_VERSION = "1.0"
NUMBER_TOKEN = r"[-+]?[0-9OoIl|.,]+"
FIELD_PATTERNS = {
    "protein_g": rf"(?:たんぱく質|タンパク質|蛋白質|protein|(?<![A-Za-z])P)\s*[:：]?\s*({NUMBER_TOKEN})\s*g",
    "fat_g": rf"(?:脂質|fat|(?<![A-Za-z])F)\s*[:：]?\s*({NUMBER_TOKEN})\s*g",
    "carbs_g": rf"(?:炭水化物|carbohydrates?|carbs?|(?<![A-Za-z])C)\s*[:：]?\s*({NUMBER_TOKEN})\s*g",
    "sugar_candidate_g": rf"(?:糖質)\s*[:：]?\s*({NUMBER_TOKEN})\s*g",
}


def _warning(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "field": field}


def _evidence(
    match: re.Match[str],
    raw_value: str,
    value: Any,
    unit: str | None,
    *,
    status: str = "candidate",
) -> dict[str, Any]:
    return {
        "raw_text": match.group(0),
        "raw_value": raw_value,
        "value": value,
        "unit": unit,
        "status": status,
        "confidence": None,
    }


def _parse_number(raw_value: str, field: str) -> tuple[float | None, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    value = unicodedata.normalize("NFKC", str(raw_value or "")).strip()
    translated = value.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"}))
    if translated != value:
        warnings.append(
            _warning(
                "ocr_numeric_substitution",
                f"Numeric OCR substitutions were applied to {value!r}.",
                field,
            )
        )
    if "," in translated:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", translated):
            translated = translated.replace(",", "")
        else:
            warnings.append(_warning("malformed_decimal", f"Rejected ambiguous number {value!r}.", field))
            return None, warnings
    if translated.count(".") > 1 or not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", translated):
        warnings.append(_warning("malformed_number", f"Rejected malformed number {value!r}.", field))
        return None, warnings
    number = float(translated)
    limit = 10000.0 if field == "calories_kcal" else 1000.0
    if number < 0 or number > limit:
        warnings.append(_warning("invalid_value", f"Rejected out-of-range value {value!r}.", field))
        return None, warnings
    return number, warnings


def _basis_evidence(text: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    patterns = (
        ("per_100g", r"100\s*g\s*(?:あたり|当たり)"),
        ("per_100ml", r"100\s*ml\s*(?:あたり|当たり)"),
        ("per_package", r"(?:1|一)\s*(?:包装|袋|パック|容器)\s*(?:あたり|当たり)"),
        ("per_serving", r"(?:1|一)\s*食(?:分)?\s*(?:あたり|当たり)"),
        ("per_item", r"(?:1|一)\s*個\s*(?:あたり|当たり)"),
    )
    evidence: list[dict[str, Any]] = []
    for basis, pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            evidence.append(_evidence(match, match.group(0), basis, None))
    unique = sorted({candidate["value"] for candidate in evidence})
    if len(unique) == 1:
        for candidate in evidence:
            candidate["status"] = "selected"
        return unique[0], evidence, []
    if len(unique) > 1:
        for candidate in evidence:
            candidate["status"] = "ambiguous"
        return "unknown", evidence, [
            _warning("basis_conflict", "Multiple nutrition bases were detected.", "basis"),
            _warning("multiple_nutrition_blocks", "The label may contain multiple nutrition blocks."),
        ]
    return "unknown", [], [_warning("basis_unknown", "Nutrition basis could not be determined.", "basis")]


def _select_unique_field(
    field: str,
    evidence: list[dict[str, Any]],
) -> tuple[float | None, list[dict[str, Any]]]:
    values = {candidate["value"] for candidate in evidence if candidate.get("value") is not None}
    if len(values) == 1:
        selected = next(iter(values))
        for candidate in evidence:
            candidate["status"] = "selected" if candidate.get("value") == selected else "rejected"
        return float(selected), []
    if len(values) > 1:
        for candidate in evidence:
            candidate["status"] = "ambiguous"
        return None, [
            _warning("multiple_values", f"Conflicting values were detected for {field}.", field),
            _warning("multiple_nutrition_blocks", "The label may contain multiple nutrition blocks."),
        ]
    return None, []


def parse_nutrition_label_text(text: str) -> dict[str, Any]:
    """Parse OCR-like label text without mutating input or asserting source trust."""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    warnings: list[dict[str, Any]] = []
    field_evidence: dict[str, list[dict[str, Any]]] = {}
    nutrition = {
        "basis": "unknown",
        "calories_kcal": None,
        "protein_g": None,
        "fat_g": None,
        "carbs_g": None,
        "sugar_g": None,
        "fiber_g": None,
        "salt_g": None,
    }

    basis, basis_entries, basis_warnings = _basis_evidence(normalized)
    nutrition["basis"] = basis
    if basis_entries:
        field_evidence["basis"] = basis_entries
    warnings.extend(basis_warnings)

    energy_pattern = (
        rf"(?:(?:熱量|エネルギー|カロリー)\s*[:：]?\s*)?"
        rf"({NUMBER_TOKEN})\s*(kcal|kJ)"
    )
    energy_entries: list[dict[str, Any]] = []
    kcal_values: list[float] = []
    kj_values: list[float] = []
    for match in re.finditer(energy_pattern, normalized, flags=re.IGNORECASE):
        raw_value = match.group(1)
        unit = match.group(2).lower()
        value, number_warnings = _parse_number(raw_value, "calories_kcal")
        warnings.extend(number_warnings)
        energy_entries.append(_evidence(match, raw_value, value, unit))
        if value is not None and unit == "kcal":
            kcal_values.append(value)
        elif value is not None:
            kj_values.append(value)
    if energy_entries:
        field_evidence["calories_kcal"] = energy_entries

    unique_kcal = sorted(set(kcal_values))
    unique_kj = sorted(set(kj_values))
    if len(unique_kcal) == 1:
        nutrition["calories_kcal"] = unique_kcal[0]
        for candidate in energy_entries:
            candidate["status"] = (
                "selected"
                if candidate.get("unit") == "kcal" and candidate.get("value") == unique_kcal[0]
                else "supporting"
            )
        if unique_kj:
            warnings.append(_warning("mixed_energy_units", "kcal was preferred over the accompanying kJ value.", "calories_kcal"))
            converted = unique_kj[0] / 4.184
            if abs(converted - unique_kcal[0]) > max(5.0, unique_kcal[0] * 0.1):
                warnings.append(_warning("energy_unit_mismatch", "kcal and kJ values are not consistent.", "calories_kcal"))
    elif len(unique_kcal) > 1:
        warnings.extend(
            [
                _warning("multiple_values", "Conflicting kcal values were detected.", "calories_kcal"),
                _warning("multiple_nutrition_blocks", "The label may contain multiple nutrition blocks."),
            ]
        )
        for candidate in energy_entries:
            candidate["status"] = "ambiguous"
    elif len(unique_kj) == 1:
        nutrition["calories_kcal"] = round(unique_kj[0] / 4.184, 2)
        for candidate in energy_entries:
            candidate["status"] = "derived"
            candidate["value"] = nutrition["calories_kcal"]
            candidate["unit"] = "kcal"
        warnings.append(_warning("kj_converted", "kJ was converted to a kcal candidate and requires confirmation.", "calories_kcal"))
    elif len(unique_kj) > 1:
        warnings.append(_warning("multiple_values", "Conflicting kJ values were detected.", "calories_kcal"))
        for candidate in energy_entries:
            candidate["status"] = "ambiguous"

    for field, pattern in FIELD_PATTERNS.items():
        entries: list[dict[str, Any]] = []
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            raw_value = match.group(1)
            target_field = "carbs_g" if field == "sugar_candidate_g" else field
            value, number_warnings = _parse_number(raw_value, target_field)
            warnings.extend(number_warnings)
            entries.append(_evidence(match, raw_value, value, "g"))
        if not entries:
            continue
        field_evidence[field] = entries
        if field == "sugar_candidate_g":
            warnings.append(_warning("sugar_not_carbs", "糖質 alone was not mapped to carbohydrates.", "carbs_g"))
            continue
        selected, selection_warnings = _select_unique_field(field, entries)
        nutrition[field] = selected
        warnings.extend(selection_warnings)

    size_pattern = rf"内容量\s*[:：]?\s*({NUMBER_TOKEN})\s*(g|ml)"
    size_entries: list[dict[str, Any]] = []
    for match in re.finditer(size_pattern, normalized, flags=re.IGNORECASE):
        value, number_warnings = _parse_number(match.group(1), "size")
        warnings.extend(number_warnings)
        size_text = f"{value:g}{match.group(2).lower()}" if value is not None else None
        size_entries.append(_evidence(match, match.group(1), size_text, match.group(2).lower()))
    if size_entries:
        selected_sizes = {entry["value"] for entry in size_entries if entry.get("value")}
        for entry in size_entries:
            entry["status"] = "selected" if len(selected_sizes) == 1 else "ambiguous"
        field_evidence["size"] = size_entries
        if len(selected_sizes) > 1:
            warnings.append(_warning("multiple_values", "Conflicting content sizes were detected.", "size"))

    if basis in {"per_100g", "per_100ml"}:
        for field in ("protein_g", "fat_g", "carbs_g"):
            value = nutrition.get(field)
            if value is not None and value > 100:
                nutrition[field] = None
                warnings.append(_warning("invalid_per_100_value", f"{field} exceeds 100 for a per-100 basis.", field))
                for candidate in field_evidence.get(field, []):
                    candidate["status"] = "rejected"

    for field in ("calories_kcal", "protein_g", "fat_g", "carbs_g"):
        if nutrition[field] is None:
            warnings.append(_warning("missing_nutrition_field", f"{field} requires user confirmation.", field))

    severe_codes = {
        "basis_conflict",
        "malformed_decimal",
        "malformed_number",
        "invalid_value",
        "multiple_values",
        "multiple_nutrition_blocks",
    }
    confidence = 0.45 if any(item["code"] in severe_codes for item in warnings) else 0.75
    return {
        "parser_version": NUTRITION_LABEL_PARSER_VERSION,
        "raw_text": str(text or ""),
        "nutrition": deepcopy(nutrition),
        "field_evidence": deepcopy(field_evidence),
        "warnings": deepcopy(warnings),
        "extraction_confidence": confidence,
    }


__all__ = ["NUTRITION_LABEL_PARSER_VERSION", "parse_nutrition_label_text"]
