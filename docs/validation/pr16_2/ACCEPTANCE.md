# PR16.2 Acceptance

## Local Results

Date: 2026-08-25

- PASS: Tesseract 5.5.2 with `jpn+eng` starts locally.
- PASS: synthetic Japanese nutrition label upload and preview.
- PASS: Calories 120 kcal, Protein 3.2 g, Fat 1.5 g, Carbs 20.1 g, `per_item` extraction.
- PASS: OCR Candidate remains unconfirmed and review-required.
- PASS: shared Editor and explicit Confirmation produce Daily Nutrition at 100% coverage.
- PASS: preprocessing v1.1 synthetic-label OCR approximately 551 ms across enhanced/source variants; same-image cache hit approximately 7 ms.
- PASS: synthetic label retains 4/4 fields after preprocessing changes: 120 kcal / P3.2g / F1.5g / C20.1g.
- PASS: 4032×3024 input is not downscaled; low-resolution input is upscaled toward a 2200px long edge with a 3x cap.
- PASS: camera and upload inputs render through one shared image-byte pipeline; identical bytes reuse the same SHA cache entry.
- PASS: camera and upload selection render at 390px with no horizontal overflow in the local Streamlit app.
- PASS: preprocessing approximately 29 ms; Candidate generation approximately 0.1 ms for the synthetic fixture.
- PASS: blank image returns the manual Editor without a page exception.
- PASS: normal Streamlit startup approximately 0.5 seconds in AppTest without OCR initialization.
- PASS: JSON and Supabase adapters restore confirmed Calories/P/F/C.
- PASS: Canonical, Repository, and source scans exclude image bytes, raw OCR text, and `capture_metadata`.
- PASS: Python 3.12.13 environment resolves the complete project dependency set with pinned Streamlit 1.59.0.
- PASS: the recommended native-camera/photo uploader is the first capture option; Quick Camera requests 1080p.
- PASS: at a 390px browser viewport, document/body scroll width remains 390px and Quick Camera uses the available 324px content width.

The local label is generated test media, not a photographed commercial package. Real-label accuracy is not claimed by local validation.

## Cloud Acceptance

Status: **PARTIAL - NOT MERGE-READY**

Dedicated app: https://body-recomp-dashboard-pr16-2-test.streamlit.app/

- PASS: the PR branch deployed and the Streamlit dashboard started without an application exception.
- PASS: Smart Food Capture and the label-image upload section render in the hosted app.
- PARTIAL: iPhone Camera → OCR → Candidate → Editor → Confirmation works, but small-label OCR is limited by Camera input quality.
- PASS: metadata-only `ocr_runtime` panel and preprocessing v1.1 deployed from the latest PR head.
- PASS: hosted Tesseract execution and the basic iPhone Camera flow run without a page exception.
- PENDING: preprocessing v1.1 real-label accuracy comparison and Supabase-backed Personal Food Master save/reboot checks.

Hosted runtime metadata before OCR:

- Tesseract executable: detected
- Tesseract version: 5.5.0
- Languages: `eng`, `jpn`, `osd`
- Japanese / English: available
- Pillow: 11.3.0
- pytesseract: 0.3.13
- OCR runtime: not initialized
- OCR cache: empty, 0 / 8 entries
- Repository: `SupabaseFoodMasterRepository`, connected
- Supabase: configured in the dedicated app
- Fallback active: false
- Python / Streamlit after the runtime-pin deployment: pending

Required before Draft removal:

1. Confirm `packages.txt` installs Tesseract with `jpn` and `eng` data by executing hosted OCR.
2. Upload 3-5 real Japanese nutrition-label images.
3. Confirm preview, OCR, Candidate, Editor correction, and Daily Nutrition.
4. Configure the dedicated app's Food Knowledge secrets and confirm optional Personal Food Master save and immediate same-name P/F/C restore.
5. Reboot the app and confirm the saved Food Master value restores again.
6. Confirm an unreadable image reaches manual fallback.
7. Confirm a repeated image reports a cache hit.
8. Inspect Supabase Food Knowledge rows and confirm no image, OCR text, token, or bounding-box payload exists.

## Mobile Camera Acceptance

Use an iPhone or equivalent smartphone against the dedicated PR16.2 Test App:

1. Open Smart Food Capture and expand `栄養ラベル画像から追加`.
2. Use `高画質で撮影・写真から選択（推奨）` and select the native camera or a library photo.
3. Repeat with `クイック撮影（1080p）` and allow camera permission.
4. Photograph a Japanese nutrition label and confirm the preview is readable without horizontal overflow.
5. Run OCR and confirm Calories / Protein / Fat / Carbohydrates and basis flow into one review-required Candidate.
6. Correct any OCR errors in the shared Editor and explicitly confirm the item.
7. Confirm Daily Food and Daily Nutrition reflect only the corrected values.
8. Repeat OCR for the same captured image during the same process and confirm a cache hit and no extra OCR execution.
9. Confirm Repository revision and food counts remain unchanged before Confirmation.
10. Inspect persisted stores and confirm the camera image, processed image, and raw OCR text are absent.

Record device/browser, viewport width, camera permission result, OCR/cache timing, Candidate/Editor/Confirmation result, and any layout issue. The camera path must preserve the same Supabase save, immediate search, and reboot restoration checks used by uploaded images.

### Camera Quality Comparison

Repeat the same label after preprocessing v1.1 and compare it with the original Camera result and a high-quality Upload. Input metadata appears before OCR; preprocessing and OCR metadata is under `画像・OCR診断（内容非表示）`.

| Method | Input px | File bytes | OCR px | Fields / 4 | Basis | OCR ms | Manual corrections |
| --- | --- | ---: | --- | ---: | --- | ---: | ---: |
| `camera_input` default baseline | pending |  |  |  |  |  |  |
| Quick Camera 1080p | pending |  |  |  |  |  |  |
| Native Camera via uploader | pending |  |  |  |  |  |  |
| Photo-library upload | pending |  |  |  |  |  |  |

Do not put image hashes, raw OCR text, food names, nutrition values, or non-orientation EXIF data in this comparison.

Before uploading a label, enable `Food Knowledge詳細を表示` and record only these metadata fields:

- Tesseract executable detected, version, and available languages
- `jpn` / `eng` availability
- Pillow / pytesseract versions
- Python / Streamlit versions
- OCR initialized status and cache entry count
- Repository type, connection status, and fallback state

Do not record or screenshot Secrets, image content, OCR text, food names, or nutrition values outside the per-image acceptance table.

## Real Label Results

Use at least three and preferably five Japanese commercial-product labels.

| Case | OCR | Calories | Protein | Fat | Carbs | Basis | User corrections | OCR ms | Cache-hit ms | Confirmation |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | --- |
| Label 1 | pending |  |  |  |  |  |  |  |  | pending |
| Label 2 | pending |  |  |  |  |  |  |  |  | pending |
| Label 3 | pending |  |  |  |  |  |  |  |  | pending |
| Label 4 | optional |  |  |  |  |  |  |  |  | pending |
| Label 5 | optional |  |  |  |  |  |  |  |  | pending |

For each successful case, confirm Candidate generation, shared Editor correction, explicit Confirmation, and Daily Food totals. For one remembered food, confirm immediate same-name Personal Food Master restore, reboot the app, then confirm the same Calories/P/F/C restore again.

Also record one same-image cache hit and one unreadable-image manual fallback. Compare normal Smart Food Search timing before and after OCR initialization. Verify Repository revision and food counts do not change before Confirmation, and inspect persisted stores/logs for metadata fields rather than copying image or OCR payloads into the report.

PR16.2 remains Draft and is not Merge-ready until these hosted cases pass.
