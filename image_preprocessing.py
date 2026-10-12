from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import time
from typing import Any


IMAGE_PREPROCESSING_VERSION = "1.2"
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
    line_removed: Any
    ruled_line_ratio: float
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


def _long_runs(dark: Any, length: int, axis: int) -> Any:
    """Mark pixels that belong to an unbroken dark run of at least `length` along `axis`."""
    import numpy as np

    size = dark.shape[axis]
    if length > size:
        return np.zeros_like(dark)
    pad = [(0, 0), (0, 0)]
    pad[axis] = (1, 0)
    counts = np.pad(dark.astype(np.int32), pad).cumsum(axis=axis)
    upper = np.take(counts, np.arange(length, size + 1), axis=axis)
    lower = np.take(counts, np.arange(0, size - length + 1), axis=axis)
    window_full = (upper - lower) == length
    # Expand each full window start back over the `length` pixels it covers.
    starts = np.pad(window_full.astype(np.int32), pad).cumsum(axis=axis)
    starts_size = starts.shape[axis]
    index = np.arange(1, size + 1)
    hi = np.take(starts, np.minimum(index, starts_size - 1), axis=axis)
    lo = np.take(starts, np.maximum(index - length, 0), axis=axis)
    return (hi - lo) > 0


def remove_ruled_lines(gray: Any) -> tuple[Any, float]:
    """Binarize a label and erase long table rules that break Tesseract layout analysis.

    Japanese nutrition panels are almost always boxed tables. Their borders and row
    rules make Tesseract's page segmentation drop the enclosed text, so this variant
    flattens uneven lighting, binarizes, and paints long horizontal/vertical dark runs
    white. Character strokes are much shorter than table rules and survive.
    """
    import numpy as np

    Image, _, _ = _pillow_modules()
    from PIL import ImageFilter

    width, height = gray.size
    # Estimate the paper/background brightness on a small copy (fast), so glare and
    # shading do not turn into black blobs after thresholding.
    small_scale = max(1, max(width, height) // 400)
    small = gray.resize((max(1, width // small_scale), max(1, height // small_scale)), Image.Resampling.BILINEAR)
    background = small.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(4))
    background = background.resize((width, height), Image.Resampling.BILINEAR)
    pixels = np.asarray(gray, dtype=np.float32)
    flattened = np.clip(pixels / np.maximum(np.asarray(background, dtype=np.float32), 1.0) * 255.0, 0, 255)

    histogram, _ = np.histogram(flattened, bins=256, range=(0, 256))
    total = flattened.size
    cumulative = histogram.cumsum()
    cumulative_mean = (histogram * np.arange(256)).cumsum()
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (cumulative_mean[-1] * cumulative / total - cumulative_mean) ** 2 / (
            cumulative * (total - cumulative)
        )
    otsu = int(np.nanargmax(between)) if np.isfinite(between).any() else 160
    threshold = min(max(otsu, 110), 215)
    dark = flattened < threshold

    horizontal = _long_runs(dark, max(40, width // 12), axis=1)
    vertical = _long_runs(dark, max(40, height // 8, width // 12), axis=0)
    rules = horizontal | vertical
    # Rules are often antialiased; widen the mask by one pixel on each side.
    rules = rules | np.roll(rules, 1, axis=0) | np.roll(rules, -1, axis=0) | np.roll(rules, 1, axis=1) | np.roll(rules, -1, axis=1)
    cleaned = np.where(dark & ~rules, 0, 255).astype(np.uint8)
    ratio = float(rules.mean())
    return Image.fromarray(cleaned), round(ratio, 5)


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
    line_removed, ruled_line_ratio = remove_ruled_lines(enhanced_source.convert("L"))
    elapsed_ms = (time.perf_counter() - started) * 1000
    return PreprocessedLabelImage(
        primary=primary,
        fallback=fallback,
        line_removed=line_removed,
        ruled_line_ratio=ruled_line_ratio,
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
    "remove_ruled_lines",
]
