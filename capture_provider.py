from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from capture_models import CaptureObservation, build_capture_observation
from nutrition_label_parser import parse_nutrition_label_text


@dataclass(frozen=True)
class CaptureRequest:
    payload: Any
    image_sha256: str | None = None
    identifiers: tuple[tuple[str, str], ...] = ()
    hints: dict[str, Any] = field(default_factory=dict)


class CaptureProvider(ABC):
    """Convert one input channel into an observation without persistence access."""

    capture_channel: str
    provider_name: str
    provider_version: str

    @abstractmethod
    def capture(self, request: CaptureRequest) -> CaptureObservation:
        raise NotImplementedError


class FakeOcrProvider(CaptureProvider):
    """Deterministic PR16.1 provider; it performs no image or OCR work."""

    capture_channel = "label_ocr"
    provider_name = "fake_ocr"
    provider_version = "1.0"

    def capture(self, request: CaptureRequest) -> CaptureObservation:
        raw_text = str(request.payload or "")
        parsed = parse_nutrition_label_text(raw_text)
        evidence = deepcopy(parsed["field_evidence"])
        provider_confidence = request.hints.get("ocr_confidence", parsed["extraction_confidence"])
        for candidates in evidence.values():
            for candidate in candidates:
                candidate["confidence"] = provider_confidence
        identifiers = [
            {"type": identifier_type, "value": identifier_value}
            for identifier_type, identifier_value in request.identifiers
        ]
        return build_capture_observation(
            capture_channel=self.capture_channel,
            provider=self.provider_name,
            provider_version=self.provider_version,
            image_sha256=request.image_sha256,
            raw_text=raw_text,
            suggested_name=request.hints.get("suggested_name"),
            field_evidence=evidence,
            identifiers=identifiers,
            warnings=parsed["warnings"],
            extraction_confidence=provider_confidence,
        )


__all__ = ["CaptureProvider", "CaptureRequest", "FakeOcrProvider"]
