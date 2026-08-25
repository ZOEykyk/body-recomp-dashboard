# Label OCR Runtime

## Flow

```text
Native camera / photo selection, quick camera, or JPG / JPEG / PNG upload
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

The primary mobile path is `st.file_uploader()` so iOS and Android can use their native camera or photo chooser. The secondary quick path is `st.camera_input(resolution="1080p", width="stretch")`. Both return image bytes to the same preprocessing and OCR entry point; input origin does not create a separate downstream branch or alter the PR16.1 Capture contract.

## Runtime

- Pillow applies EXIF orientation, RGB normalization, bounded resize, grayscale, autocontrast, and light contrast enhancement.
- Images with a long edge below 2200px are upscaled toward 2200px, capped at 3x. Typical 4032px iPhone photos retain source resolution; only images above 4200px on the long edge are bounded for runtime safety.
- The decoded source RGB stays at its original oriented resolution. RGB conversion is in-memory and does not re-encode or recompress JPEG data.
- Enhanced grayscale and source RGB both run through OCR. Selection prioritizes complete Calories/P/F/C extraction, then OCR confidence and token count.
- Sharpening was tested but is not enabled in v1.1 because it reduced extraction in the regression fixture. The source variant remains available when contrast enhancement performs worse.
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

The captured or uploaded image, processed variants, raw OCR text, and token-level data are never written to:

- Supabase
- Local JSON / JSONL Food Knowledge
- Canonical Daily Record
- records.csv
- application logs

Only user-confirmed name, quantity, unit, nutrition, and existing source metadata may use the existing Daily Food and `explicit_user_label` persistence paths.

## Cloud Runtime Diagnostics

The existing `Food Knowledge詳細を表示` panel includes a metadata-only `ocr_runtime` section for hosted acceptance. It reports Tesseract detection/version/languages, `jpn` and `eng` availability, Pillow and pytesseract versions, initialization status, and cache entry counts. Repository type, connection status, and fallback state remain in the adjacent `runtime` section.

The diagnostic contract never includes executable paths, environment values, secrets, image hashes, cache keys, image data, OCR text, food names, or nutrition values. The environment probe does not initialize the OCR engine.

After image selection, the UI shows only width, height, byte size, format, EXIF presence, and EXIF orientation. After OCR it adds preprocessing dimensions/scale, per-variant field count/confidence/time, selected variant, and cache status. Other EXIF fields are intentionally excluded because they may contain private device or location data.

## Failure Behavior

Corrupt images, missing Tesseract/language data, execution failure, timeout, unreadable labels, and missing nutrition fields remain page-local errors. The UI creates or retains an unconfirmed manual candidate so the user can continue in the shared Editor.

## Deployment

Python dependencies are declared in `requirements.txt`, with Streamlit pinned to `1.59.0` for the camera resolution contract. The project development runtime is Python 3.12 as declared in `.python-version`; Streamlit 1.59 requires Python 3.10 or newer. Streamlit Community Cloud must use Python 3.12 in its deployment settings because an existing Cloud app's Python version is not changed by repository files. System packages are declared in `packages.txt` as Tesseract plus English and Japanese language data. Cloud Acceptance must remain pending until a deployed PR branch is exercised with 3-5 real Japanese labels, manual correction, Personal Food Master restore, reboot persistence, cache reuse, failure fallback, and Supabase privacy inspection.

## Barcode Extension

Future barcode and product lookup providers continue to implement `CaptureProvider` and emit generic `identifiers` such as `{"type": "ean13", "value": "..."}`. PR16.2 adds no OCR field to the FoodCandidate top level and no barcode schema or migration.
