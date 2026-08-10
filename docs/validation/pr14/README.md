# PR14 UI Validation

Validated against the actual Streamlit application on 2026-08-09.

## Environment

- Streamlit: local app at `http://localhost:8518/`
- Desktop viewport: 1280 x 900
- Mobile viewport: 390 x 844
- Browser console errors: 0
- Import save action: not executed

## Results

- Safe compatibility input displayed all 12 normalization changes.
- Canonical Schema 1.0 validation succeeded after normalization.
- Canonical preview showed the exact JSON that would be persisted.
- Invalid input displayed all six errors with JSON paths, suggestions, and non-auto-fixable status.
- Mobile error cards and normalization rows wrapped without horizontal overflow.
- Existing Body Score and Today's Metrics sections remained present.
- Canonical Schema 1.0 input displayed the zero-change normalization state.

## Screenshots

- `normalization-desktop-1280.png`
- `canonical-preview-desktop-1280.png`
- `schema-errors-desktop-1280.png`
- `normalization-mobile-390.png`
- `canonical-preview-mobile-390.png`
- `schema-errors-mobile-390.png`

The screenshots contain preview and validation states only. No fixture was persisted to `records.csv`.
