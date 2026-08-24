# PR16.2 Acceptance

## Local Results

Date: 2026-08-24

- PASS: Tesseract 5.5.2 with `jpn+eng` starts locally.
- PASS: synthetic Japanese nutrition label upload and preview.
- PASS: Calories 120 kcal, Protein 3.2 g, Fat 1.5 g, Carbs 20.1 g, `per_item` extraction.
- PASS: OCR Candidate remains unconfirmed and review-required.
- PASS: shared Editor and explicit Confirmation produce Daily Nutrition at 100% coverage.
- PASS: first OCR approximately 393 ms; same-image cache hit approximately 7 ms.
- PASS: preprocessing approximately 34 ms; Candidate generation approximately 0.1 ms.
- PASS: blank image returns the manual Editor without a page exception.
- PASS: normal Streamlit startup approximately 0.5 seconds in AppTest without OCR initialization.
- PASS: JSON and Supabase adapters restore confirmed Calories/P/F/C.
- PASS: Canonical, Repository, and source scans exclude image bytes, raw OCR text, and `capture_metadata`.

The local label is generated test media, not a photographed commercial package. Real-label accuracy is not claimed by local validation.

## Cloud Acceptance

Status: **PARTIAL - NOT MERGE-READY**

Dedicated app: https://body-recomp-dashboard-pr16-2-test.streamlit.app/

- PASS: the PR branch deployed and the Streamlit dashboard started without an application exception.
- PASS: Smart Food Capture and the label-image upload section render in the hosted app.
- PENDING: verify the metadata-only `ocr_runtime` panel after this acceptance diagnostic commit deploys.
- PENDING: hosted Tesseract execution and real-label accuracy checks.
- PENDING: Supabase-backed Personal Food Master save/reboot checks because production secrets are not configured in the dedicated app.

Required before Draft removal:

1. Confirm `packages.txt` installs Tesseract with `jpn` and `eng` data by executing hosted OCR.
2. Upload 3-5 real Japanese nutrition-label images.
3. Confirm preview, OCR, Candidate, Editor correction, and Daily Nutrition.
4. Configure the dedicated app's Food Knowledge secrets and confirm optional Personal Food Master save and immediate same-name P/F/C restore.
5. Reboot the app and confirm the saved Food Master value restores again.
6. Confirm an unreadable image reaches manual fallback.
7. Confirm a repeated image reports a cache hit.
8. Inspect Supabase Food Knowledge rows and confirm no image, OCR text, token, or bounding-box payload exists.

Before uploading a label, enable `Food Knowledge詳細を表示` and record only these metadata fields:

- Tesseract executable detected, version, and available languages
- `jpn` / `eng` availability
- Pillow / pytesseract versions
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
