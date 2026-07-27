# PR13 Acceptance Test

## Automated commands

```bash
python3 -m py_compile app.py bodyos_import.py dashboard.py dashboard_aggregation.py workout_history.py
python3 scripts/validate_pr13_import.py
python3 scripts/validate_pr13_workout.py
python3 scripts/validate_pr13_dashboard.py
python3 scripts/validate_pr13_alias.py
python3 scripts/validate_pr13.py
```

Existing PR7 through PR12 validation scripts must also pass.

## 2026-07-26 fixture

Use `tests/fixtures/pr13_acceptance_2026-07-26.json`.

Expected:

- Weight: 83.2kg
- Sleep: 8 hours
- Condition: 8
- Steps: 11,786
- Meals: breakfast, snack, lunch, and dinner
- Workout: one session, six exercises, 75 minutes
- Listed workout sets are retained in order

The implementation brief says 19 sets, but its listed repetitions contain 20 sets:

```text
4 + 4 + 3 + 3 + 3 + 3 = 20
```

BodyOS does not silently discard a set to force 19. Product acceptance should correct either the expected count or one listed exercise.

## Import scenarios

1. Preview before save shows date, basic metrics, food count, session count, exercise count, set count, conflicts, and warnings.
2. First import creates one daily row.
3. Identical re-import keeps one daily row, one Workout session, six exercises, and twenty listed sets.
4. Changed same-day content updates that row and receives a different content identity.
5. `更新` changes supplied sections only.
6. `置換` replaces the day projection.
7. `中止` preserves existing conflicting dates.
8. Unknown Schema versions and duplicate dates within one payload are rejected.
9. Legacy JSON is accepted through the adapter and emits a warning.
10. Exported Schema 1.0 JSON re-imports with the same date and Workout meaning.

## Nutrition scenarios

1. Explicit item or daily nutrition wins.
2. Otherwise Personal, Official, or Generic resolved nutrition may be used.
3. Fallback estimates are not stored as known import nutrition.
4. Unknown calories remain `null`; the unknown count is stored and displayed.
5. Compatible numeric quantities use `calculate_lookup_total()` once.
6. Free-text quantities are retained but not multiplied.
7. Dashboard calories and PFC equal persisted aggregate values.

## Alias scenarios

1. NFKC, case, and whitespace normalization is lightweight and deterministic.
2. One normalized Alias maps to at most one Food per owner.
3. AI-origin metadata may be stored only after explicit user approval.
4. Unapproved proposals are not persisted or searchable.
5. Adding an Alias never merges Food records.
6. Apply PR12 migration first, then `supabase/migrations/20260727_pr13_food_alias.sql`.
7. Run `supabase/verification/pr13_alias_acceptance.sql`.

## Historical compatibility

- App startup does not save or migrate `records.csv`.
- Automated validation compares `records.csv` SHA-256 before and after.
- Existing free-text meals and workouts remain readable.
- Body Score and Workout Intelligence public interfaces do not change.
- PR13 Alias rollback is `supabase/rollback/20260727_pr13_food_alias_rollback.sql`.

## Manual UI

1. Start the actual Streamlit app.
2. Paste the acceptance fixture and select `取り込み内容を確認`.
3. Confirm the Preview values and the 20-set specification note.
4. Save to a temporary test copy, not production `records.csv`.
5. Confirm Import Diagnostics and Food Resolution Summary.
6. Confirm Dashboard metrics and structured Workout history.
7. Export the saved date and re-import it.
8. Validate desktop and 390px mobile widths with no Streamlit exception.
