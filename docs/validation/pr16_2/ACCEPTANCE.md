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

Status: **NOT COMPLETE**

Required before Draft removal:

1. Deploy the PR16.2 branch to a dedicated Streamlit Community Cloud test app.
2. Confirm `packages.txt` installs Tesseract with `jpn` and `eng` data.
3. Upload 3-5 real Japanese nutrition-label images.
4. Confirm preview, OCR, Candidate, Editor correction, and Daily Nutrition.
5. Confirm optional Personal Food Master save and immediate same-name P/F/C restore.
6. Reboot the app and confirm the saved Food Master value restores again.
7. Confirm an unreadable image reaches manual fallback.
8. Confirm a repeated image reports a cache hit.
9. Inspect Supabase Food Knowledge rows and confirm no image, OCR text, token, or bounding-box payload exists.

PR16.2 remains Draft and is not Merge-ready until these hosted cases pass.
