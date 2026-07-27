# PR13 Streamlit Acceptance Validation

Validated with the actual Streamlit application on 2026-07-27 using
`tests/fixtures/pr13_acceptance_2026-07-26.json`.

## Results

- Import Preview: 1 daily record, 4 meal items, 1 workout session,
  6 exercises, 20 sets, and 75 minutes.
- Dashboard after save: 83.2 kg, 8 hours sleep, condition 8,
  11,786 steps, 2,200 kcal, and 145 g protein.
- Structured workout history displays the program, duration, exercise
  names, weights, repetitions, exercise count, and set count.
- Re-importing the identical JSON updates the existing daily row instead
  of adding another row.
- Re-importing the identical JSON reports 0 encounters saved and
  4 duplicate encounters skipped.
- The compatibility fixture projects all 11 foods from persisted structured
  meals. Snacks display as `ドトール スイートポテト、コーヒー、ジェラート`.
- Meal calories use the same persisted nutrition path as the 1,588 kcal daily
  total: breakfast 298, lunch 100 known kcal with one unknown item, snacks
  150 known kcal with one unknown item, and dinner 1,040 kcal.
- Missing event, alcohol detail, and drinks never expose `nan`, `None`, or an
  empty collection. Array notes render as natural text separated by `／`.
- Editing the Previewed compatibility JSON from 11,786 to 12,000 steps hides
  the stale save action and requires a new Preview.
- Saving that new Preview updates the existing day in place. The Dashboard
  immediately shows 12,000 steps while retaining 11 foods, 1 workout session,
  6 exercises, 20 sets, and 1,588 kcal.
- Repeating the exact 12,000-step JSON keeps one daily row and reports
  `Encounter saved: 0 / Duplicate skipped: 11`.
- Desktop width: 1280 px.
- Mobile width: 390 px, with no document-level horizontal overflow.
- No browser errors were emitted by the active Streamlit application.
- `records.csv` in the source worktree was not modified.

## Screenshots

- `dashboard-summary-desktop-1280.png`: saved dashboard aggregates.
- `dashboard-desktop-1280.png`: structured workout history.
- `dashboard-mobile-390.png`: responsive dashboard summary.
- `import-desktop-1280.png`: import preview and idempotent re-import result.
- `import-mobile-390.png`: responsive import result.
- `compatibility-import-desktop-1280.png`: compatibility input with 11 foods.
- `compatibility-reimport-desktop-1280.png`: identical re-import with all
  11 Food Encounters skipped as duplicates.
- `dashboard-projection-desktop-1280.png`: completed meal, calorie, missing
  value, Workout, and notes Projection.
- `same-day-update-desktop-1280.png`: Dashboard immediately showing 12,000
  steps after the changed same-day update.

## Compatibility Input

`tests/fixtures/pr13_compatibility_input_2026-07-26.json` validates the
actual alternate Schema 1.0 input shapes:

- scalar sleep value
- singular `snack`
- object-form quantity and unit
- direct item calories and macro fields
- array-form daily notes

The actual Streamlit application previewed and saved 11 foods, one workout
session, six exercises, 20 sets, and 75 minutes. The dashboard showed
1,588 known kcal, 16.5 g protein, and two foods with unknown calories after
the shared Food Resolver resolved six of the eight non-explicit items.
Re-importing the identical JSON kept one daily row and reported
`Encounter saved: 0 / Duplicate skipped: 11`.

## Acceptance Fixture Note

The written PR requirement calls the workout a 19-set session, while the
listed repetitions contain 20 sets:

`4 + 4 + 3 + 3 + 3 + 3 = 20`.

PR13 preserves every listed set and therefore stores and displays 20 sets.
No set is silently discarded to force the contradictory total.
