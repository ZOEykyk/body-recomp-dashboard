# Data Standard

## Source of Truth

`records.csv` is the current source of truth. All import, dashboard, scoring, and recalculation logic must preserve compatibility with existing CSV records.

`dashboard.py` is a rendering layer only. It may derive display columns such as labels, rolling averages, and chart helper fields at runtime, but it must not introduce required CSV columns or change the stored record contract.

Raw user records are immutable by default. New parsing, scoring, calorie, or display rules must not silently rewrite historical rows during ordinary app launch. Corrected rules apply to new records, new imports, explicit edits, and records explicitly re-imported by the user. Historical migration requires a separate user-confirmed workflow.

## Standard JSON Import Shape

Future ChatGPT logs should move toward this shape:

```json
{
  "schema_version": "1.0",
  "bodyos_standard_version": "1.0",
  "date": "2026-07-06",
  "mode": "NORMAL",
  "event_name": "",
  "weight": 85.2,
  "steps": 8200,
  "sleep_hours": 7.5,
  "condition": "良い",
  "meals": {
    "breakfast": "プロテイン、トマトジュース",
    "lunch": "うどん、とり天",
    "dinner": "鶏むね肉、白米、サラダ",
    "snacks": "オイコス"
  },
  "drinks": "コーヒー、カフェラテ",
  "workout": {
    "performed": true,
    "menu": "ベンチプレス 90kg 5,6,6,4"
  },
  "coach_comment": "歩数と食事は良好。明日は睡眠を増やす。"
}
```

## Core Fields

- `schema_version`: Version of the import payload shape.
- `bodyos_standard_version`: Version of BodyOS semantic rules.
- `date`: Record date.
- `mode`: `NORMAL`, `EVENT`, `RECOVERY`, or `BULK`.
- `event_name`: Event label when applicable.
- `weight`: Body weight.
- `steps`: Daily steps.
- `sleep_hours`: Sleep duration.
- `condition`: Physical or mental condition.
- `meals`: Meal text grouped by breakfast, lunch, dinner, and snacks.
- `drinks`: Workday or other drinks.
- `workout`: Training performed and details.
- `coach_comment`: Coaching note or daily comment.

## Compatibility Rules

- Japanese keys and English keys may both be accepted.
- `workout.performed`, `trained`, and `筋トレ有無` should normalize consistently.
- `workout.menu`, `筋トレ内容`, and similar fields should normalize into one workout detail string.
- Explicit kcal values should be prioritized.
- Estimated calories are approximate and should be presented as estimates.
- Manual calories override automatic estimates if available.
- New CSV columns should be optional unless a migration PR explicitly changes the schema.
- Existing records must remain readable after normalization.
- Missing body weight values are not real zero weights. Dashboard averages, rolling averages, charts, and predictions must ignore missing weight values.
- Meal text that clearly means no meal must be treated as 0 kcal and must not receive fallback calories.

## Missing Weight Rules

For body-weight calculations, the following values are missing:

- `null`
- empty string
- `NaN`
- `0`
- `"0"`
- invalid non-numeric values

Weekly, monthly, and seven-day average weight calculations must exclude missing weights from both the numerator and denominator. A week with no valid weight displays `—`; a week with one valid weight displays that one value. Weight charts should not draw a point at zero for missing days, and missing daily weight should display as `—`.

The stored CSV remains backward-compatible. Existing historical rows are not automatically rewritten just because a newer missing-value rule exists.

## Calorie Data Rules

- Explicit kcal values in meal text have the highest priority.
- Dictionary-based calorie estimates should feel realistic, not perfectly precise.
- If only part of a meal is detected, unknown items should not silently become 0 kcal.
- Zero-meal text such as `なし`, `食べていない`, `未食`, `抜き`, `スキップ`, `朝食なし`, `昼食なし`, `夕食なし`, `晩御飯なし`, and `晩ご飯なし` is an explicit no-meal signal for breakfast, lunch, dinner, and snacks. It should return 0 kcal with no fallback estimate.
- Unknown non-empty meal text may still use fallback estimation.
- Manual user-entered calories are authoritative for that meal.

## Body Score Data Rules

Body Score should be recalculable from stored records. Imported manual Body Score values may be preserved separately, but current dashboard logic should prefer the app's latest calculated score when recalculating.

Score component raw values remain stored as raw points in the CSV. The maximum score for each component is defined once in `bodyos_standard.py` as `SCORE_COMPONENT_MAXIMA`:

- `体重スコア`: 15
- `食事スコア`: 20
- `タンパク質スコア`: 15
- `歩数スコア`: 10
- `筋トレスコア`: 10
- `睡眠スコア`: 10
- `体調スコア`: 10
- `飲酒スコア`: 10

Dashboard component achievement percentages are render-time derived values:

```text
achievement_rate = actual_score / maximum_score * 100
```

The derived percentage is bounded between 0% and 100%. Missing or not-applicable component values display as `—` and must not be silently converted to 0%. These derived percentages are not stored in `records.csv` and do not change Body Score calculation rules.

## Workout Intelligence Data Rules

`workout_intelligence.py` defines Workout Intelligence v1. The public interface is:

```python
analyze_workout(record: dict, history: list[dict] | None = None) -> dict
```

The function reads existing workout text fields such as `筋トレ内容`, `workout.menu`, and `workout_detail`. It must not change the stored CSV schema.

The result may include parsed exercises, PR candidates, next targets, progression context, confidence, and a short summary. Workout parsing is approximate and should preserve the raw workout text as the source of truth.

## BodyOS Standard v1.0

`bodyos_standard.py` defines the first reusable BodyOS rule engine. The public scoring interface is:

```python
calculate_bodyos_score(record: dict) -> dict
```

The function accepts normalized CSV-style records and future JSON-style records where practical. It returns:

- `metadata`
- `overall`
- `steps`
- `sleep`
- `nutrition`
- `workout`
- `recovery`
- `coach`

For current Streamlit and CSV compatibility, the result also includes top-level compatibility fields:

- `bodyos_standard_version`
- normalized `mode`
- `Body Score`
- score component columns such as `体重スコア`, `食事スコア`, and `飲酒スコア`
- `components`, a nested dictionary containing the same component breakdown
- `overall.component_max_scores`, the shared maximum-score metadata for interpreting component achievement rates

Future app, API, and AI Coach code should call this interface instead of reimplementing daily evaluation rules.

`calculate_bodyos_score()` is a pure function. It must not mutate the input `record`; callers receive a separate evaluation result.
