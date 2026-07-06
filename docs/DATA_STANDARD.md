# Data Standard

## Source of Truth

`records.csv` is the current source of truth. All import, dashboard, scoring, and recalculation logic must preserve compatibility with existing CSV records.

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

## Calorie Data Rules

- Explicit kcal values in meal text have the highest priority.
- Dictionary-based calorie estimates should feel realistic, not perfectly precise.
- If only part of a meal is detected, unknown items should not silently become 0 kcal.
- Manual user-entered calories are authoritative for that meal.

## Body Score Data Rules

Body Score should be recalculable from stored records. Imported manual Body Score values may be preserved separately, but current dashboard logic should prefer the app's latest calculated score when recalculating.

## BodyOS Standard v1.0

`bodyos_standard.py` defines the first reusable BodyOS rule engine. The public scoring interface is:

```python
calculate_bodyos_score(record: dict) -> dict
```

The function accepts normalized CSV-style records and future JSON-style records where practical. It returns:

- `bodyos_standard_version`
- normalized `mode`
- `Body Score`
- score component columns such as `体重スコア`, `食事スコア`, and `飲酒スコア`
- `components`, a nested dictionary containing the same component breakdown

Future app, API, and AI Coach code should call this interface instead of reimplementing daily evaluation rules.

`calculate_bodyos_score()` is a pure function. It must not mutate the input `record`; callers receive a separate evaluation result.
