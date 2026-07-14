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

- Meal text should be parsed into structured food items before calorie estimation.
- `parse_food_text(text, meal_type)` is a pure parser interface and must not mutate inputs or historical records.
- The food parser may detect item boundaries, quantities, zero-meal text, and explicit nutrition values.
- The food parser must not own nutrition facts, public lookup data, or Food Master records.
- Parsed food items expose `brand`, `canonical_name`, `variant`, `size`, `quantity`, `unit`, `original_fragment`, `resolution`, `confidence`, `needs_review`, and `explicit_nutrition` for future Food Lookup use.
- Parser resolution values distinguish `alias_exact`, `normalized_exact`, `brand_context`, and `unresolved`. Unresolved or ambiguous foods must preserve the original fragment and set `needs_review=true`.
- Explicit nutrition extracted from user text carries `basis` and `value_origin="explicit_text"`. It maps to the `explicit_user_label` source type and is never silently replaced by official or estimated data.
- Explicit kcal values in meal text have the highest priority.
- Food Lookup runs after parsing and before the existing estimate dictionaries. A lookup result is valid only when the reviewed local catalog yields one unambiguous product/menu match.
- Lookup results expose `matched`, `nutrition`, `source`, and `match` metadata. `source` identifies the official product page or official nutrition table used to validate the local catalog item.
- Lookup results also expose `status` (`matched`, `ambiguous`, `not_found`, or `skipped_explicit_nutrition`), `match_type`, `confidence`, `needs_review`, `candidates`, and the original parsed identity. Ambiguous results are not selected automatically.
- A parsed brand is a required match constraint. Brand-less parsed items may use an identity-only match only when it is unique.
- Catalog entries require category, validity dates, active status, complete nullable nutrition fields, and source verification metadata. Invalid, inactive, expired, or duplicate active entries are excluded from normal lookup.
- `calculate_lookup_total(lookup_result, quantity, unit)` applies only compatible `per_item`, `per_package`, `per_serving`, `per_100g`, `per_100ml`, or `total` bases. It returns a review-required result rather than guessing for incompatible units.
- Every nutrition source uses the shared `food_source_models.py` contract: `source_id`, `source_type`, `publisher`, `source_ref`, `captured_at`, `verified_at`, `valid_from`, `valid_to`, `product_version`, `reviewer`, `verification_status`, `confidence`, and `notes`.
- Default source priority is: explicit user label, official product page, official nutrition table, official API/catalog, BodyOS verified, user verified, general reference, legacy dictionary, then fallback estimate.
- Rejected, superseded, expired, or out-of-validity sources cannot be selected. Stale selected sources and conflicting values remain reviewable through `needs_review`; equal-priority conflicting values are not selected automatically.
- Personal Food Master data is separate from `records.csv`: food records, aliases, source candidates, usage statistics, and append-only encounters are stored through `FoodMasterRepository`.
- A food encounter is not trusted knowledge. Estimated or unresolved food is stored as a candidate; only reviewed candidates or authoritative verified sources may become an active reusable personal food.
- Food Master writes occur only for newly saved manual records and newly imported JSON records. Normal dashboard loading, CSV history loading, and Body Score recalculation must not rewrite historical rows or backfill encounters.
- Food Master records use `owner_user_id` as the contract owner field (with legacy `user_id` retained for compatibility), and include scope, category, default quantity/unit, notes, schema version, creator, updater, aliases, review status, and usage statistics. Review statuses are `pending_review`, `reviewed`, or `rejected`.
- Candidate deduplication uses the exact personal identity tuple: brand, canonical name, variant, and size. Different variants or sizes must remain separate candidates.
- Encounter records are append-only and carry a stable idempotency key based on owner, record date, meal type, normalized fragment, save/import operation identity, and a normalized meal-content hash. Replaying identical content must not append a line, create a food, or increment use count; changed content or quantity creates a new encounter.
- The current JSON/JSONL Food Master adapter is a local MVP. It has no durable hosted backend yet, so Streamlit Cloud restarts or redeploys can discard Food Master data. Existing GitHub persistence applies to `records.csv` only.

## Nutrition Intelligence v1

- Nutrition Intelligence is computed at render time and never adds columns to `records.csv`, rewrites historical records, or changes Body Score.
- The public pure result includes engine/ruleset/target versions, day status, expected progress, normalized Nutrition Score, confidence, totals, targets, component breakdown, strengths, priorities, actions, comparisons, data quality, and rule trace.
- Score allocation is calories 20, protein 20, fat 15, carbohydrates 10, fiber 10, salt 10, vegetables 10, and hydration 5. Unavailable metrics are excluded from available points, then earned points are normalized to 100; missing data is never silently scored as zero.
- Day status is `morning_only`, `partial_day`, `complete_day`, or `unknown_completion`. Morning uses 25% and partial day uses 60% target progress by default; complete days use 100%. Historical dated records with dinner are treated as complete, while current incomplete records retain cautious language.
- Target defaults are 2,200 kcal; protein 1.6g/kg when a positive body weight is supplied, otherwise 120g; fat 25-35% energy; carbohydrates 35-55%; fiber 21g; salt <=7.5g; vegetables three servings; and hydration 2,000ml only when a real hydration input exists.
- Confidence is separate from score and uses resolved/estimated item ratio, source quality, macro coverage, unresolved count, and completion state. Explicit or official values support stronger wording; fallback-heavy or incomplete data is presented as a reference value.
- Recommendation precedence is data reliability, calorie excess/deficit, protein deficiency, fat excess, vegetables/fiber, salt, then optimization. Actions are deterministic, non-contradictory, and capped at three.
- Previous-day comparison reports values and direction without calling every increase an improvement. Seven-day averages use only valid complete historical days, need two days to display, and use four days before strong trend wording.
- Rule traces keep the inputs, component result, and points for every score adjustment. This supports validation and a future optional LLM wording layer without giving that layer authority over nutrition data.
- If lookup is unresolved, ambiguous, variant-mismatched, or size-mismatched, it must not invent a trusted value; the existing dictionary/fallback path remains available.
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
