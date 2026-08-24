from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import time
from typing import Any


IMAGE_PREPROCESSING_VERSION = "1.0"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
TARGET_LONG_EDGE = 2200


class ImagePreprocessingError(ValueError):
    """A sanitized image validation or preprocessing failure."""


@dataclass(frozen=True)
class PreprocessedLabelImage:
    primary: Any
    fallback: Any
    width: int
    height: int
    source_format: str | None
    elapsed_ms: float


def _pillow_modules() -> tuple[Any, Any, Any]:
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError as exc:
        raise ImagePreprocessingError("Image processing is unavailable.") from exc
    return Image, ImageEnhance, ImageOps


def preprocess_label_image(image_bytes: bytes) -> PreprocessedLabelImage:
    """Decode and lightly normalize an uploaded label without writing it to disk."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ImagePreprocessingError("The uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImagePreprocessingError("The uploaded image is too large.")

    started = time.perf_counter()
    Image, ImageEnhance, ImageOps = _pillow_modules()
    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            source_format = opened.format
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise ImagePreprocessingError("The uploaded image dimensions are too large.")
            normalized = ImageOps.exif_transpose(opened).convert("RGB")
    except ImagePreprocessingError:
        raise
    except Exception as exc:
        raise ImagePreprocessingError("The uploaded image could not be decoded.") from exc

    longest = max(normalized.size)
    if longest and longest != TARGET_LONG_EDGE:
        scale = min(TARGET_LONG_EDGE / longest, 2.0)
        if scale != 1.0:
            resized = tuple(max(1, round(value * scale)) for value in normalized.size)
            normalized = normalized.resize(resized, Image.Resampling.LANCZOS)

    fallback = normalized.copy()
    primary = ImageOps.autocontrast(normalized.convert("L"), cutoff=1)
    primary = ImageEnhance.Contrast(primary).enhance(1.15)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return PreprocessedLabelImage(
        primary=primary,
        fallback=fallback,
        width=normalized.width,
        height=normalized.height,
        source_format=source_format,
        elapsed_ms=round(elapsed_ms, 3),
    )


__all__ = [
    "IMAGE_PREPROCESSING_VERSION",
    "ImagePreprocessingError",
    "PreprocessedLabelImage",
    "preprocess_label_image",
]
