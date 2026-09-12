from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import time
from typing import Any


IMAGE_PREPROCESSING_VERSION = "1.1"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
MIN_OCR_LONG_EDGE = 2200
MAX_OCR_LONG_EDGE = 4200
MAX_UPSCALE_FACTOR = 3.0


class ImagePreprocessingError(ValueError):
    """A sanitized image validation or preprocessing failure."""


@dataclass(frozen=True)
class PreprocessedLabelImage:
    primary: Any
    fallback: Any
    source_width: int
    source_height: int
    width: int
    height: int
    fallback_width: int
    fallback_height: int
    file_size_bytes: int
    source_format: str | None
    exif_present: bool
    exif_orientation: int | None
    scale_factor: float
    resized: bool
    elapsed_ms: float


def _pillow_modules() -> tuple[Any, Any, Any]:
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError as exc:
        raise ImagePreprocessingError("Image processing is unavailable.") from exc
    return Image, ImageEnhance, ImageOps


def inspect_label_image_metadata(image_bytes: bytes) -> dict[str, Any]:
    """Return non-content image metadata without exposing EXIF payloads."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ImagePreprocessingError("The uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImagePreprocessingError("The uploaded image is too large.")
    Image, _, _ = _pillow_modules()
    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise ImagePreprocessingError("The uploaded image dimensions are too large.")
            exif = opened.getexif()
            orientation = exif.get(274) if exif else None
            return {
                "width": int(opened.width),
                "height": int(opened.height),
                "file_size_bytes": len(image_bytes),
                "format": str(opened.format or "unknown").upper(),
                "exif_present": bool(exif),
                "exif_orientation": int(orientation) if isinstance(orientation, int) else None,
            }
    except ImagePreprocessingError:
        raise
    except Exception as exc:
        raise ImagePreprocessingError("The uploaded image could not be decoded.") from exc


def preprocess_label_image(image_bytes: bytes) -> PreprocessedLabelImage:
    """Decode and lightly normalize an uploaded label without writing it to disk."""
    started = time.perf_counter()
    metadata = inspect_label_image_metadata(image_bytes)
    Image, ImageEnhance, ImageOps = _pillow_modules()
    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            normalized = ImageOps.exif_transpose(opened).convert("RGB")
    except ImagePreprocessingError:
        raise
    except Exception as exc:
        raise ImagePreprocessingError("The uploaded image could not be decoded.") from exc

    # Preserve the decoded source variant. RGB conversion changes pixel mode only;
    # no JPEG re-encoding or additional compression occurs in this in-memory path.
    fallback = normalized.copy()
    longest = max(normalized.size)
    scale_factor = 1.0
    if longest and longest < MIN_OCR_LONG_EDGE:
        scale_factor = min(MIN_OCR_LONG_EDGE / longest, MAX_UPSCALE_FACTOR)
    elif longest > MAX_OCR_LONG_EDGE:
        scale_factor = MAX_OCR_LONG_EDGE / longest
    enhanced_source = normalized
    if scale_factor != 1.0:
        resized_size = tuple(max(1, round(value * scale_factor)) for value in normalized.size)
        enhanced_source = normalized.resize(resized_size, Image.Resampling.LANCZOS)

    primary = ImageOps.autocontrast(enhanced_source.convert("L"), cutoff=1)
    primary = ImageEnhance.Contrast(primary).enhance(1.15)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return PreprocessedLabelImage(
        primary=primary,
        fallback=fallback,
        source_width=metadata["width"],
        source_height=metadata["height"],
        width=primary.width,
        height=primary.height,
        fallback_width=fallback.width,
        fallback_height=fallback.height,
        file_size_bytes=metadata["file_size_bytes"],
        source_format=metadata["format"],
        exif_present=metadata["exif_present"],
        exif_orientation=metadata["exif_orientation"],
        scale_factor=round(scale_factor, 4),
        resized=scale_factor != 1.0,
        elapsed_ms=round(elapsed_ms, 3),
    )


__all__ = [
    "IMAGE_PREPROCESSING_VERSION",
    "MAX_OCR_LONG_EDGE",
    "MAX_UPSCALE_FACTOR",
    "MIN_OCR_LONG_EDGE",
    "ImagePreprocessingError",
    "PreprocessedLabelImage",
    "inspect_label_image_metadata",
    "preprocess_label_image",
]
