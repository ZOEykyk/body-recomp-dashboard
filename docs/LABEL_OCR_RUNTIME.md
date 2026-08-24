# Label OCR Runtime

## Flow

```text
JPG / JPEG / PNG upload
-> Pillow preprocessing
-> LabelOcrProvider / Tesseract jpn+eng
-> CaptureObservation
-> Nutrition Label Parser
-> existing FoodCandidate and shared Editor
-> explicit user Confirmation
-> Daily Food
-> optional Personal Food Master
```

PR16.2 adds no alternate food model and no persistence API. OCR modules do not import Repository, Food Master, Supabase, or Daily Record code.

## Runtime

- Pillow applies EXIF orientation, RGB normalization, bounded resize, grayscale, autocontrast, and light contrast enhancement.
- The grayscale variant runs first. The normalized RGB variant runs only when no nutrition field is detected, and the safer result is selected by field count then OCR confidence.
- pytesseract uses Tesseract with `jpn+eng`, OEM 3, PSM 6, and a bounded timeout.
- Pillow and pytesseract are lazy imports, so ordinary Food Search does not initialize OCR.
- Common OCR character spacing is normalized only for Parser input. Raw extraction remains separate and candidates always require review.

## Cache

The bounded process-local cache key contains:

- image SHA-256
- OCR engine name and version
- preprocessing version
- OCR language

The cache is memory-only and is cleared by process restart or deployment. It prevents repeated OCR work on Streamlit reruns without creating durable image or text storage.

## Privacy

The uploaded image, processed variants, raw OCR text, and token-level data are never written to:

- Supabase
- Local JSON / JSONL Food Knowledge
- Canonical Daily Record
- records.csv
- application logs

Only user-confirmed name, quantity, unit, nutrition, and existing source metadata may use the existing Daily Food and `explicit_user_label` persistence paths.

## Cloud Runtime Diagnostics

The existing `Food Knowledge詳細を表示` panel includes a metadata-only `ocr_runtime` section for hosted acceptance. It reports Tesseract detection/version/languages, `jpn` and `eng` availability, Pillow and pytesseract versions, initialization status, and cache entry counts. Repository type, connection status, and fallback state remain in the adjacent `runtime` section.

The diagnostic contract never includes executable paths, environment values, secrets, image hashes, cache keys, image data, OCR text, food names, or nutrition values. The environment probe does not initialize the OCR engine.

## Failure Behavior

Corrupt images, missing Tesseract/language data, execution failure, timeout, unreadable labels, and missing nutrition fields remain page-local errors. The UI creates or retains an unconfirmed manual candidate so the user can continue in the shared Editor.

## Deployment

Python dependencies are declared in `requirements.txt`. Streamlit Community Cloud system packages are declared in `packages.txt` as Tesseract plus English and Japanese language data. Cloud Acceptance must remain pending until a deployed PR branch is exercised with 3-5 real Japanese labels, manual correction, Personal Food Master restore, reboot persistence, cache reuse, failure fallback, and Supabase privacy inspection.

## Barcode Extension

Future barcode and product lookup providers continue to implement `CaptureProvider` and emit generic `identifiers` such as `{"type": "ean13", "value": "..."}`. PR16.2 adds no OCR field to the FoodCandidate top level and no barcode schema or migration.
