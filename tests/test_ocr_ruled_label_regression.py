"""Regression coverage for the real-label OCR failure (boxed Japanese nutrition tables).

Earlier tests fed parser-ready text to a fake engine, so they passed while real
photographed labels produced 0/4 fields: Tesseract `--psm 6` drops text enclosed by
table rules, and OCR glues the gram unit onto values (`4.5g` -> `4.59`).
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
import unittest

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from image_preprocessing import remove_ruled_lines
from label_ocr_runtime import LabelOcrProvider, OcrRuntimeCache, capture_label_image
from nutrition_label_parser import parse_nutrition_label_text


JAPANESE_FONT_CANDIDATES = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
)


def _japanese_font() -> str | None:
    return next((path for path in JAPANESE_FONT_CANDIDATES if Path(path).exists()), None)


def _tesseract_with_japanese() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract

        return {"jpn", "eng"} <= set(pytesseract.get_languages(config=""))
    except Exception:
        return False


def _boxed_label(font_path: str, px: int = 64) -> Image.Image:
    rows = [
        ("栄養成分表示 1袋(45g)当たり", ""),
        ("エネルギー", "230kcal"),
        ("たんぱく質", "4.5g"),
        ("脂質", "12.3g"),
        ("炭水化物", "26.1g"),
        ("食塩相当量", "0.6g"),
    ]
    font = ImageFont.truetype(font_path, px)
    row_height = int(px * 1.65)
    width, height = px * 15, row_height * len(rows) + px // 2
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for index, (label, value) in enumerate(rows):
        y = px // 4 + index * row_height
        draw.text((px // 2, y), label, font=font, fill="black")
        if value:
            draw.text((width - px // 2, y), value, font=font, fill="black", anchor="ra")
        rule_y = y + row_height - px // 4
        draw.line((0, rule_y, width, rule_y), fill="black", width=max(1, px // 14))
    draw.rectangle((0, 0, width - 1, height - 1), outline="black", width=max(2, px // 9))
    return image


def _jpeg(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


class RuledLineRemovalTests(unittest.TestCase):
    def test_table_rules_are_erased_but_character_strokes_survive(self) -> None:
        image = Image.new("L", (1200, 600), 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 1189, 589), outline=0, width=6)
        draw.line((10, 300, 1189, 300), fill=0, width=4)
        # Character-sized strokes, including a horizontal one like `ー`.
        draw.line((100, 100, 160, 100), fill=0, width=6)
        draw.line((300, 80, 300, 160), fill=0, width=6)
        cleaned, ratio = remove_ruled_lines(image)
        self.assertEqual(cleaned.mode, "L")
        self.assertEqual(cleaned.size, image.size)
        self.assertGreater(ratio, 0)
        self.assertEqual(cleaned.getpixel((600, 12)), 255)
        self.assertEqual(cleaned.getpixel((12, 450)), 255)
        self.assertEqual(cleaned.getpixel((600, 300)), 255)
        self.assertEqual(cleaned.getpixel((130, 100)), 0)
        self.assertEqual(cleaned.getpixel((300, 120)), 0)

    def test_uneven_lighting_does_not_blacken_background(self) -> None:
        gradient = Image.linear_gradient("L").resize((800, 400)).point(lambda value: 120 + value // 2)
        cleaned, _ = remove_ruled_lines(gradient)
        dark_ratio = sum(1 for value in cleaned.getdata() if value == 0) / (800 * 400)
        self.assertLess(dark_ratio, 0.02)


class OcrDamagedTextParserTests(unittest.TestCase):
    def _nutrition(self, text: str) -> dict:
        return parse_nutrition_label_text(text)["nutrition"]

    def test_gram_unit_glued_as_digit_is_removed_with_review_warning(self) -> None:
        parsed = parse_nutrition_label_text("エネルギー 230kcal\nたんぱく質 4.59\n脂質 12.39\n炭水化物 26.18")
        nutrition = parsed["nutrition"]
        self.assertEqual(
            [nutrition["protein_g"], nutrition["fat_g"], nutrition["carbs_g"]],
            [4.5, 12.3, 26.1],
        )
        codes = [warning["code"] for warning in parsed["warnings"]]
        self.assertEqual(codes.count("ocr_glued_unit_digit"), 3)

    def test_two_decimal_value_with_explicit_unit_is_kept(self) -> None:
        self.assertEqual(self._nutrition("脂質 0.05g")["fat_g"], 0.05)
        self.assertEqual(self._nutrition("たんぱく質(g) 4.59")["protein_g"], 4.59)

    def test_lowercase_single_letters_are_not_pfc_labels(self) -> None:
        nutrition = self._nutrition("たんぱく質 4.5g\np 12.3g\nf 3g\nc 9g")
        self.assertEqual(nutrition["protein_g"], 4.5)
        self.assertIsNone(nutrition["fat_g"])
        self.assertIsNone(nutrition["carbs_g"])
        self.assertEqual(self._nutrition("P 12g F 15g C 14g")["fat_g"], 15.0)

    def test_damaged_carbohydrate_and_protein_labels_map_to_fields(self) -> None:
        nutrition = self._nutrition("次水化物 26.1g\nたんばぱく質 4.5g")
        self.assertEqual(nutrition["carbs_g"], 26.1)
        self.assertEqual(nutrition["protein_g"], 4.5)
        self.assertEqual(self._nutrition("炭水化 9.7g")["carbs_g"], 9.7)

    def test_explicit_carbohydrate_still_preferred_over_sugar(self) -> None:
        nutrition = self._nutrition("炭水化物 47.2g\n糖質 44.0g")
        self.assertEqual(nutrition["carbs_g"], 47.2)
        self.assertEqual(nutrition["sugar_g"], 44.0)


@unittest.skipUnless(_tesseract_with_japanese() and _japanese_font(), "Tesseract jpn+eng and a Japanese font are required")
class RealTesseractBoxedLabelTests(unittest.TestCase):
    def test_boxed_label_close_up_extracts_core_fields(self) -> None:
        label = _boxed_label(_japanese_font())
        photo = label.resize((label.width * 2, label.height * 2), Image.Resampling.LANCZOS)
        photo = photo.filter(ImageFilter.GaussianBlur(1.0))
        result = capture_label_image(_jpeg(photo), provider=LabelOcrProvider(cache=OcrRuntimeCache()))
        nutrition = result["candidate"]["nutrition"]
        expected = {"calories_kcal": 230.0, "protein_g": 4.5, "fat_g": 12.3, "carbs_g": 26.1}
        correct = [field for field, value in expected.items() if nutrition.get(field) == value]
        wrong = [
            field
            for field, value in expected.items()
            if nutrition.get(field) is not None and nutrition.get(field) != value
        ]
        self.assertGreaterEqual(len(correct), 3, msg=f"correct={correct} nutrition={nutrition}")
        self.assertEqual(wrong, [], msg=f"nutrition={nutrition}")
        self.assertFalse(result["candidate"]["confirmed"])


if __name__ == "__main__":
    unittest.main()
