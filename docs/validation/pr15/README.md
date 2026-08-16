# PR15 UI Validation

Validated against the actual Streamlit app on 2026-08-16.

## Environment

- Streamlit: `http://localhost:8519`
- Desktop viewport: 1280 x 900
- Mobile viewport: 390 x 844
- Browser console errors: none
- Horizontal overflow: none at either viewport

## Scenarios

- `みたらし団子`: 3 items purchased, 2 consumed, 122 kcal per item.
  The consumed total is 244 kcal and the partial-consumption state remains visible.
- `ホテル朝食ブッフェ`: consumed with unknown nutrition. Calories remain unknown
  instead of being coerced to 0 kcal, and the review warning remains visible.
- `ファミチキ`: search displays the official FamilyMart candidate with an
  `High` confidence source badge and an editable nutrition form.
- `PR15 TEST 団子`: a new user-label food with three purchased and two consumed
  retains its entered per-unit nutrition. Daily and Canonical totals are 244 kcal,
  P 4.8 g, F 1.2 g, and C 55 g; re-search restores the original 122 kcal,
  P 2.4 g, F 0.6 g, and C 27.5 g per item from Personal Food Master.
  Existing items and stale Streamlit widget state with `basis=unknown` are
  automatically repaired without requiring a manual basis selection.
- Canonical Builder: generated Schema 1.0 validates with `PASS` and requires
  `0 changes` from the compatibility normalizer.
- Only consumed quantities appear in canonical meals and nutrition totals.
- Existing dashboard sections and the CSV save action continue to render.

## Screenshots

- `smart-food-capture-desktop-1280.png`
- `smart-food-capture-mobile-390.png`
- `food-suggestion-desktop-1280.png`
- `user-label-partial-consumption-desktop-1280.png`
- `canonical-builder-desktop-1280.png`
- `canonical-builder-mobile-390.png`
