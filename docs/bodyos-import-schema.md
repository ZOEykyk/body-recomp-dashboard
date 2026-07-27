# BodyOS Import Schema 1.0

The normative machine-readable contract is `schemas/bodyos-daily-log.schema.json`.

## Envelope

A single daily object, an array of daily objects, or this batch envelope is accepted:

```json
{
  "schema_version": "1.0",
  "records": [
    {
      "schema_version": "1.0",
      "date": "2026-07-26"
    }
  ]
}
```

`schema_version` is required for new-format records. Legacy BodyOS/ChatGPT objects without a version pass through the compatibility adapter and produce a warning. Unknown versions are rejected.

## Missing values

- Unknown numeric values are `null`, not zero.
- Missing calorie and macro values remain `null`.
- Free-text quantity is stored in `quantity_text` and is not multiplied.
- `0` is a valid value only where the schema explicitly permits it.

## Meals

Meals are grouped under `breakfast`, `lunch`, `dinner`, `snacks`, and `drinks`.

```json
{
  "meals": {
    "breakfast": [
      {
        "name": "オイコス PRO",
        "quantity": 1,
        "unit": "本",
        "nutrition": {
          "calories_kcal": 100,
          "protein_g": 18,
          "fat_g": 0,
          "carbs_g": 6,
          "basis": "per_item"
        }
      }
    ]
  }
}
```

Nutrition precedence for import aggregation is:

1. Explicit item or daily nutrition
2. Personal Food Master
3. Official catalog
4. Generic catalog
5. Unknown

Fallback estimates are not saved as known import nutrition. Existing manual-entry calorie estimation remains backward compatible.

## Workout

Workouts use one session with ordered exercises and sets:

```json
{
  "workout": {
    "performed": true,
    "program_name": "Week3 Day2【Hypertrophy】",
    "workout_type": "hypertrophy",
    "duration_minutes": 75,
    "exercises": [
      {
        "name": "インクラインダンベルプレス",
        "equipment": "dumbbell",
        "sets": [
          {
            "weight_kg": 32,
            "reps": 10,
            "rpe": null,
            "completed": true,
            "set_type": null
          }
        ]
      }
    ]
  }
}
```

Legacy `reps: [10, 10, 9, 8]` is converted to four ordered sets. Workout text is also converted where the existing parser can identify exercises and sets.

## Idempotency

- Daily identity: owner plus calendar date.
- Re-importing identical content updates the same daily row.
- Food Encounter idempotency continues to include the normalized meal-content fingerprint.
- Structured workout exercises and sets live inside the same atomic daily-row projection, so re-import does not append duplicate sessions or sets.

## Conflict behavior

When a date already exists, the UI offers:

- `更新`: update supplied sections while preserving compatible stored values.
- `置換`: replace the stored daily row with the imported projection.
- `中止`: skip conflicting dates.

The default is `更新`. Unconditional append is not supported.
