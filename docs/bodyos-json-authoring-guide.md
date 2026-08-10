# BodyOS JSON Authoring Guide

## Single Source of Truth

BodyOS Daily Logの唯一の機械可読契約は
[`schemas/bodyos-daily-log.schema.json`](../schemas/bodyos-daily-log.schema.json)です。

Schema versionは`1.0`です。AI、人間、Import UIのいずれがJSONを作る場合も、
[`tests/fixtures/schema_1_0_canonical_example.json`](../tests/fixtures/schema_1_0_canonical_example.json)
をコピー元として使用してください。Compatibility Inputは入力時だけ許される限定的な形式であり、保存・ExportされるJSONはCanonical Schema 1.0です。

## Canonical Structure

日次objectの正式top-level keyは次のとおりです。

- `schema_version`
- `date`
- `weight`
- `sleep`
- `condition`
- `steps`
- `meals`
- `alcohol`
- `workout`
- `notes`
- `mode`
- `event_name`
- `nutrition_totals`

`sleep`は`{"hours": 7.5}`、食事区分は`breakfast`, `lunch`, `dinner`, `snacks`, `drinks`を使用します。

## Food Nutrition

食品の栄養値は食品objectの`nutrition`に記載します。

```json
{
  "name": "オイコス PRO",
  "quantity": 1,
  "unit": "個",
  "notes": null,
  "nutrition": {
    "calories_kcal": 100,
    "protein_g": 18,
    "fat_g": 0,
    "carbs_g": 6,
    "basis": "total"
  }
}
```

正式な栄養keyは次の4つです。

- `calories_kcal`
- `protein_g`
- `fat_g`
- `carbs_g`

値が不明な場合は`null`を使用します。欠損PFCを推定して埋めてはいけません。

## Basis Enum

Schema 1.0で許可される`basis`は次の値だけです。

- `per_item`
- `per_package`
- `per_serving`
- `per_100g`
- `per_100ml`
- `total`
- `unknown`
- `null`

「推定値であること」と「値のbasis」は別概念です。食品1件全体の栄養値を推定した場合も`basis: "total"`とし、推定であることは食品の`notes`に記載します。`estimated_total`, `estimated`, `label`はbasisではなく、Schema enum外なので使用できません。

## Workout Structure

Schema 1.0は1日につき1つの`workout` objectを持ち、種目を`workout.exercises`へ直接記載します。

```json
{
  "workout": {
    "performed": true,
    "program_name": "DAY1",
    "workout_type": "strength",
    "duration_minutes": 60,
    "notes": null,
    "exercises": [
      {
        "name": "ベンチプレス",
        "equipment": "barbell",
        "notes": null,
        "sets": [
          {
            "weight_kg": 90,
            "reps": 5,
            "rpe": 8,
            "completed": true,
            "set_type": "work"
          }
        ]
      }
    ]
  }
}
```

複数の`workout.sessions`はSchema 1.0に存在しません。セット種別は`type`ではなく`set_type`を使用します。

## Common Errors

| NG | OK | 理由 |
|---|---|---|
| `condition_score` | `condition` | 正式top-level keyへ統一 |
| `sleep_hours` | `sleep.hours` | Canonical sleep objectを使用 |
| top-level `nutrition` | `nutrition_totals` | 日次合計の正式key |
| `calories` | `calories_kcal` | 単位を含む正式key |
| `protein` | `protein_g` | 単位を含む正式key |
| `fat` | `fat_g` | 単位を含む正式key |
| `carbs` | `carbs_g` | 単位を含む正式key |
| `workout.sessions` | `workout.exercises` | Schema 1.0は単一Workout |
| set `type` | `set_type` | 正式set key |
| `basis: "estimated_total"` | 許可されたbasis | 推定状態とbasisを混同しない |
| `summary`, `memo`, `nutrition_summary` | 正式keyへ入力側で整理 | 意味を安全に確定できない |

## Safe Compatibility Normalization

BodyOSは意味が明確で、情報損失がなく、Canonical keyとの競合がない場合だけCompatibility Inputを変換します。変換内容はPreviewのNormalization Reportへ必ず表示されます。

Canonical keyとaliasが同時にあり値が異なる場合、複数Workout session、enum外basis、未知の独自fieldは保存されません。入力側で意味を決定してから再Importしてください。

## Round Trip

Import Previewの「保存されるCanonical JSON」は、そのまま再Importできます。再Import時はCompatibility normalizationが0件になり、Schema Validation OKになることが契約です。
