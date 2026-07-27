# PR13 Implementation Notes

## Current-state investigation

### Storage

- Daily records: `records.csv`, optionally mirrored to GitHub through the Contents API.
- Meals: free-text columns in the daily CSV row. Structured nutrition was not persisted.
- Workouts: `筋トレ有無` and `筋トレ内容` text columns in the daily CSV row.
- Personal Food Knowledge: repository abstraction backed by local JSON/JSONL or the PR12 Supabase adapter.
- Supabase before PR13: `foods`, `food_aliases`, `nutrition_sources`, `nutrition_facts`, and `food_encounters`. There were no daily-record, meal, workout-session, exercise, or set tables.

### Import and mapping

- JSON entry point: the `ChatGPTログ貼り付け` section in `app.py`.
- Mapping: `JSON_KEY_ALIASES`, `get_nested_value()`, and `normalize_record()`.
- Conflict key: normalized calendar date only. Existing rows were replaced by `upsert_records()`.
- Food encounters were written after the CSV save and were intentionally non-blocking.

### Calories and PFC

- `app.py` calls the shared `Food Resolver` once per meal text.
- A supplied daily calorie total wins over the sum of meal estimates.
- PFC values were evaluated by Nutrition Intelligence but not persisted in `records.csv`.
- Unknown foods could be represented by fallback estimates, so import diagnostics could not distinguish known nutrition from guesses.

### Dashboard

- `dashboard.py` reads the in-memory DataFrame loaded from `records.csv`.
- Weight, calories, steps, and Body Score use stored CSV columns.
- Workout Intelligence reparses the stored workout text at render time.
- Several values were formatted in component functions instead of coming from one explicit aggregate contract.

### Migration impact

PR13 keeps the CSV as the compatible daily-record projection. It adds nullable structured JSON and aggregate columns only when a new or explicitly updated record is saved. Ordinary app launch does not rewrite historical rows. PR12 Food Knowledge tables remain unchanged by the import foundation.

## Implementation decisions

1. `bodyos_import.py` owns the formal schema adapter, validation, preview, diagnostics, anomaly warnings, nutrition precedence, workout normalization, and export.
2. Daily record, meals, and structured workout data are committed as one CSV row. This avoids partial daily/meal/workout success without inventing an unconfirmed production database.
3. The canonical import contract preserves unknown calories as `null`. Dashboard sums may display the known subtotal while `カロリー不明件数` remains visible.
4. Explicit nutrition is evaluated once. Otherwise Personal/Official/Generic resolution may be used. Resolver fallback is retained for existing manual estimation but is not promoted to known import nutrition.
5. Structured workouts are persisted as JSON in the compatibility row and projected back to the existing workout text for Workout Intelligence.
6. Supabase daily/workout tables are deferred until the owner/auth contract and PR12 production acceptance are complete. The import module is storage-independent so a future repository can consume the same canonical object.
