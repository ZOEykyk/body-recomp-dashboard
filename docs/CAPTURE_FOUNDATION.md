# Capture Foundation

## Contract

PR16.1 normalizes future input channels without introducing a second Food or nutrition model.

```text
CaptureProvider -> CaptureObservation -> FoodCandidateFactory
-> existing FoodCandidate -> shared Editor -> User Confirmation
-> prepare_capture_item() -> Daily Food -> optional confirm_capture_food()
```

`CaptureObservation` carries provider identity, nullable image hash, raw extraction text, field-level evidence, warnings, and generic identifiers such as `{"type": "ean13", "value": "..."}`. PR16.1 defines the identifier contract but performs no barcode scan or product lookup.

`FoodCandidateFactory` adds only nested `capture_metadata`. Existing FoodCandidate keys remain compatible. The nested metadata is ephemeral UI state and is ignored by Canonical Schema and current persistence adapters.

## Trust Boundary

- `capture_channel` records input provenance; `source_type` records nutrition authority.
- Fake OCR output is always `confirmed=false`, `needs_review=true`, and `source_type=unknown`.
- OCR confidence is extraction confidence only.
- Provider and parser modules do not import Repository code.
- Observation, parsing, candidate creation, and Editor correction perform no write.
- A user action may pass corrected values through `prepare_capture_item()` with `source_mode=user_label`.
- Optional Personal Food persistence continues through `confirm_capture_food()` and the existing `explicit_user_label` source contract.

## Nutrition Label Parser

The pure parser recognizes Japanese energy, protein, fat, carbohydrates, kcal/kJ, and existing nutrition bases. kcal takes priority over kJ. kJ-only energy is a derived candidate with a warning. 糖質 is preserved as evidence but is not assigned to `carbs_g`. Unknown basis, malformed values, conflicting values, and multiple blocks remain reviewable.

Content size evidence such as `内容量180g` is kept separate from `per_100g`; content amount never determines nutrition basis.

## PR16.2 Handoff

PR16.2 should implement a real `CaptureProvider` that accepts uploaded image bytes, performs bounded preprocessing/OCR, and returns the same `CaptureObservation`. It should reuse `food_candidate_from_observation()` and `render_food_candidate_editor()` without importing Repository code into the OCR layer.

Image upload, image persistence, Tesseract, Pillow preprocessing, OCR runtime caching, barcode scanning, external product lookup, schema migration, and database changes are intentionally outside PR16.1.
