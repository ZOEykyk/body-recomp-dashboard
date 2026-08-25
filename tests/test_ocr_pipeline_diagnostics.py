from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from nutrition_label_parser import parse_nutrition_label_text
from ocr_pipeline_diagnostics import build_ocr_pipeline_diagnostics
import smart_food_capture_ui
from streamlit.testing.v1 import AppTest


def diagnose(text: str, *, token_count: int = 12) -> dict:
    parsed = parse_nutrition_label_text(text)
    return build_ocr_pipeline_diagnostics(
        text,
        parsed,
        token_count=token_count,
        average_confidence=0.81,
        median_confidence=0.86,
    )


def render_debug_component() -> None:
    import smart_food_capture_ui as capture_ui
    from nutrition_label_parser import parse_nutrition_label_text
    from ocr_pipeline_diagnostics import build_ocr_pipeline_diagnostics

    text = "栄養成分表示 1個あたり 熱量 120kcal たんぱく質 3g 脂質 1g 炭水化物 20g"
    diagnostics = build_ocr_pipeline_diagnostics(
        text,
        parse_nutrition_label_text(text),
        token_count=12,
        average_confidence=0.81,
        median_confidence=0.86,
    )
    capture_ui._render_ocr_pipeline_debug(
        {
            "pipeline_diagnostics": diagnostics
        },
        {"image_sha256": "same", "raw_text": "SESSION ONLY OCR TEXT"},
        "same",
    )


class OcrPipelineDiagnosticsTests(unittest.TestCase):
    def test_complete_label_reports_ocr_and_parser_metadata(self) -> None:
        result = diagnose(
            "栄養成分表示 1個あたり\n"
            "熱量 120kcal\nたんぱく質 3.2g\n脂質 1.5g\n炭水化物 20.1g"
        )

        self.assertEqual(result["ocr"], {
            "token_count": 12,
            "average_confidence": 0.81,
            "median_confidence": 0.86,
        })
        self.assertEqual(
            result["recognition"]["keyword_detected"],
            {"calories": True, "protein": True, "fat": True, "carbs": True},
        )
        self.assertEqual(result["recognition"]["kcal_numeric_candidate_count"], 1)
        self.assertEqual(result["recognition"]["gram_numeric_candidate_count"], 3)
        self.assertEqual(
            result["parser"]["selected_fields"],
            ["calories_kcal", "protein_g", "fat_g", "carbs_g", "basis"],
        )
        self.assertEqual(result["parser"]["rejected_fields"], [])
        self.assertEqual(result["parser"]["basis_candidate"], "per_item")
        self.assertFalse(result["parser"]["ambiguous"])
        self.assertIsNone(result["classification"]["code"])

    def test_class_a_when_ocr_has_no_nutrition_signal(self) -> None:
        result = diagnose("商品説明 保存方法 お召し上がり方", token_count=5)
        self.assertEqual(result["classification"]["code"], "A")
        self.assertEqual(result["classification"]["stage"], "ocr_recognition")
        self.assertFalse(any(result["recognition"]["keyword_detected"].values()))

    def test_english_keyword_boundaries_do_not_treat_facts_as_fat(self) -> None:
        result = diagnose("Nutrition Facts\nEnergy 120 kcal")
        self.assertTrue(result["recognition"]["keyword_detected"]["calories"])
        self.assertFalse(result["recognition"]["keyword_detected"]["fat"])

    def test_class_b_when_keywords_are_visible_but_parser_cannot_map_values(self) -> None:
        result = diagnose("1個あたり たんぱく質 約 2g")
        self.assertEqual(result["classification"]["code"], "B")
        self.assertEqual(result["classification"]["stage"], "parser_mapping")
        self.assertTrue(result["recognition"]["keyword_detected"]["protein"])
        self.assertTrue(result["recognition"]["field_value_candidate_detected"]["protein_g"])
        self.assertEqual(result["parser"]["selected_fields"], ["basis"])

    def test_class_c_when_values_are_selected_but_basis_is_unknown(self) -> None:
        result = diagnose("熱量 120kcal たんぱく質 3.2g 脂質 1.5g 炭水化物 20.1g")
        self.assertEqual(result["classification"]["code"], "C")
        self.assertEqual(result["classification"]["stage"], "handoff_ambiguity")
        self.assertEqual(result["parser"]["basis_candidate"], "unknown")
        self.assertIn(
            {"field": "basis", "reason_codes": ["basis_unknown", "not_detected"]},
            result["parser"]["rejected_fields"],
        )

    def test_ambiguous_parser_evidence_is_class_c_with_reject_reasons(self) -> None:
        result = diagnose("1個あたり 熱量 100kcal 熱量 120kcal")
        self.assertEqual(result["classification"]["code"], "C")
        self.assertTrue(result["parser"]["ambiguous"])
        calories = next(item for item in result["parser"]["rejected_fields"] if item["field"] == "calories_kcal")
        self.assertIn("ambiguous_evidence", calories["reason_codes"])
        self.assertIn("multiple_values", calories["reason_codes"])

    def test_diagnostics_never_include_raw_text_or_nutrition_values(self) -> None:
        raw = "PRIVATE LABEL 熱量 321kcal 1個あたり"
        serialized = json.dumps(diagnose(raw), ensure_ascii=False)
        self.assertNotIn(raw, serialized)
        self.assertNotIn("PRIVATE LABEL", serialized)
        self.assertNotIn("321", serialized)
        self.assertNotIn("raw_text", serialized)


class _Expander:
    def __enter__(self) -> "_Expander":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _DebugUi:
    def __init__(self, show_raw: bool) -> None:
        self.show_raw = show_raw
        self.json_values: list[dict] = []
        self.code_values: list[str] = []

    def expander(self, *args: object, **kwargs: object) -> _Expander:
        return _Expander()

    def caption(self, *args: object, **kwargs: object) -> None:
        return None

    def json(self, value: dict, **kwargs: object) -> None:
        self.json_values.append(value)

    def checkbox(self, *args: object, **kwargs: object) -> bool:
        return self.show_raw

    def warning(self, *args: object, **kwargs: object) -> None:
        return None

    def code(self, value: str, **kwargs: object) -> None:
        self.code_values.append(value)


class OcrPipelineDebugUiTests(unittest.TestCase):
    def test_streamlit_debug_expander_is_opt_in(self) -> None:
        app = AppTest.from_function(render_debug_component).run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.label.startswith("Developer Debug") for item in app.expander))
        raw_toggle = next(item for item in app.checkbox if item.key == smart_food_capture_ui.LABEL_OCR_SHOW_RAW_KEY)
        self.assertEqual(len(app.get("code")), 0)

        app = raw_toggle.set_value(True).run()
        self.assertFalse(app.exception)
        self.assertEqual([item.value for item in app.get("code")], ["SESSION ONLY OCR TEXT"])

    def test_raw_text_requires_explicit_session_debug_option(self) -> None:
        diagnostics = diagnose("1個あたり 熱量 120kcal")
        metrics = {"pipeline_diagnostics": diagnostics}
        debug_session = {"image_sha256": "same", "raw_text": "PRIVATE OCR TEXT"}

        hidden_ui = _DebugUi(show_raw=False)
        with patch.object(smart_food_capture_ui, "st", hidden_ui):
            smart_food_capture_ui._render_ocr_pipeline_debug(metrics, debug_session, "same")
        self.assertEqual(hidden_ui.code_values, [])
        self.assertNotIn("PRIVATE OCR TEXT", json.dumps(hidden_ui.json_values, ensure_ascii=False))

        visible_ui = _DebugUi(show_raw=True)
        with patch.object(smart_food_capture_ui, "st", visible_ui):
            smart_food_capture_ui._render_ocr_pipeline_debug(metrics, debug_session, "same")
        self.assertEqual(visible_ui.code_values, ["PRIVATE OCR TEXT"])

    def test_raw_text_is_not_shown_for_a_different_image(self) -> None:
        ui = _DebugUi(show_raw=True)
        with patch.object(smart_food_capture_ui, "st", ui):
            smart_food_capture_ui._render_ocr_pipeline_debug(
                {"pipeline_diagnostics": diagnose("1個あたり 熱量 120kcal")},
                {"image_sha256": "previous", "raw_text": "PRIVATE OCR TEXT"},
                "current",
            )
        self.assertEqual(ui.code_values, [])


if __name__ == "__main__":
    unittest.main()
