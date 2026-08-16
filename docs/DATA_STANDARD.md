# Data Standard

## Source of Truth

`records.csv` is the current source of truth. All import, dashboard, scoring, and recalculation logic must preserve compatibility with existing CSV records.

`dashboard.py` is a rendering layer only. `dashboard_aggregation.py` is the common stored-value projection for metrics, meals, display text, and Workout counts. Rendering code must not independently read alternate persistence shapes or recalculate calories, PFC, or structured Workout counts.

Raw user records are immutable by default. New parsing, scoring, calorie, or display rules must not silently rewrite historical rows during ordinary app launch. Corrected rules apply to new records, new imports, explicit edits, and records explicitly re-imported by the user. Historical migration requires a separate user-confirmed workflow.

## Standard JSON Import Shape

The normative contract is `schemas/bodyos-daily-log.schema.json`; the human-readable guide is `docs/bodyos-import-schema.md`. New payloads require `schema_version: "1.0"`. Legacy payloads without a version use the compatibility adapter and emit a warning.

PR14 keeps Schema 1.0 unchanged and separates compatibility input from canonical output. Input passes through safe compatibility normalization, path-aware Schema validation, and only then the existing canonical import projection. Every automatic change is visible in Preview. Ambiguous aliases, conflicting canonical/compatibility keys, multiple Workout sessions, unknown fields, and enum-external nutrition bases are rejected rather than guessed.

```json
{
  "schema_version": "1.0",
  "date": "2026-07-06",
  "mode": "NORMAL",
  "event_name": "",
  "weight": 85.2,
  "steps": 8200,
  "sleep": {"hours": 7.5},
  "condition": 8,
  "meals": {
    "breakfast": [{"name": "プロテイン"}],
    "lunch": [{"name": "うどん"}, {"name": "とり天"}],
    "dinner": [{"name": "鶏むね肉"}, {"name": "白米"}, {"name": "サラダ"}],
    "snacks": [{"name": "オイコス"}],
    "drinks": []
  },
  "workout": {
    "performed": true,
    "program_name": "Week3 Day2",
    "duration_minutes": 75,
    "exercises": [
      {
        "name": "ベンチプレス",
        "sets": [
          {"weight_kg": 90, "reps": 5, "completed": true}
        ]
      }
    ]
  },
  "notes": "歩数と食事は良好。"
}
```

## Core Fields

- `schema_version`: Version of the import payload shape.
- `date`: Record date.
- `mode`: `NORMAL`, `EVENT`, `RECOVERY`, or `BULK`.
- `event_name`: Event label when applicable.
- `weight`: Body weight.
- `steps`: Daily steps.
- `sleep.hours`: Sleep duration.
- `condition`: Physical or mental condition.
- `meals`: Meal text grouped by breakfast, lunch, dinner, and snacks.
- `meals.drinks`: Workday or other drinks.
- `workout`: Training session, exercises, and ordered sets.
- `notes`: User note.

## Compatibility Rules

- Japanese keys and English keys may both be accepted.
- `workout.performed`, `trained`, and `筋トレ有無` should normalize consistently.
- `workout.menu`, `筋トレ内容`, and similar fields should normalize into one workout detail string.
- Explicit kcal values should be prioritized.
- Estimated calories are approximate and should be presented as estimates.
- Manual calories override automatic estimates if available.
- New CSV columns should be optional unless a migration PR explicitly changes the schema.
- PR13 adds optional structured/aggregate columns. They are populated only for new, edited, or explicitly re-imported rows; ordinary launch does not rewrite history.
- Dashboard data flows through `records.csv` -> Canonical Projection -> Dashboard Projection -> UI. Structured meal/workout JSON is preferred when present; legacy columns remain a read-compatible fallback.
- Dashboard meal calories come from each persisted structured meal section. Explicit item nutrition is resolved before Food Resolver nutrition during import; unresolved item calories remain null and are shown as partial rather than silently becoming zero.
- `snacks` is the canonical meal key. The singular compatibility key `snack` is normalized at import and Dashboard Projection boundaries.
- Display Projection converts null, NaN, `None`, empty strings, and empty arrays to `—` or `なし` as appropriate. Array notes are joined as natural text; Python collection representations must not reach the user interface.
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
- `resolve_food_text()` is the only application-level food-resolution interface. It receives parser output plus a copied Food Knowledge snapshot and never reads or writes a repository.
- The Resolver collects all candidates before selection. Product-level priority is Explicit Nutrition, Personal Food Master, Official Catalog, Generic Catalog, then Fallback.
- Lower-level `lookup_food()` remains the official-catalog adapter and must not be called directly by app, import, encounter, or Nutrition Intelligence consumers.
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
- Food Knowledge repositories may use local JSON/JSONL or normalized Supabase tables. Local JSON remains a durability-non-guaranteed MVP; Supabase is the hosted durable adapter. Existing GitHub persistence applies to `records.csv` only.
- `(owner_user_id, idempotency_key)` is unique in durable storage. Encounter insertion and usage increment occur in one RPC transaction, so retrying identical content changes neither count.
- Repository implementations expose copied personal-food and encounter snapshots plus filtered query APIs. Storage paths, serialization, credentials, and queries must not leak into Resolver or intelligence engines.
- Personal Food ownership is explicit on every repository operation. Current `local-default` ownership is a single-user bridge; future Supabase Auth maps it to `auth.uid()` and RLS prevents cross-owner access.
- Supabase nutrition sources are keyed by `(food_id, source_id)`, not `source_id` alone, because domain source IDs such as `explicit-user-label` may legitimately recur on different foods. Nutrition facts use the same food/source pair.
- Food Knowledge failover never changes `records.csv`. JSON fallback may create unsynced Food Knowledge and must be reconciled explicitly after recovery.
- Resolver counts and source provenance are runtime/encounter metadata. They are not new `records.csv` columns and do not rewrite historical calories.

## Nutrition Intelligence v1

- Nutrition Intelligence is computed at render time, consumes the shared Food Knowledge snapshot through Food Resolver, and never adds columns to `records.csv`, rewrites historical records, or changes Body Score.
- The public pure result includes engine/ruleset/target versions, day status, expected progress, normalized Nutrition Score, confidence, totals, targets, component breakdown, strengths, priorities, actions, comparisons, data quality, and rule trace.
- Score allocation is calories 20, protein 20, fat 15, carbohydrates 10, fiber 10, salt 10, vegetables 10, and hydration 5. Unavailable metrics are excluded from available points, then earned points are normalized to 100; missing data is never silently scored as zero.
- Day status is `morning_only`, `partial_day`, `complete_day`, or `unknown_completion`. Morning uses 25% and partial day uses 60% target progress by default; complete days use 100%. Historical dated records with dinner are treated as complete, while current incomplete records retain cautious language.
- Target defaults are 2,200 kcal; protein 1.6g/kg when a positive body weight is supplied, otherwise 120g; fat 25-35% energy; carbohydrates 35-55%; fiber 21g; salt <=7.5g; vegetables three servings; and hydration 2,000ml only when a real hydration input exists.
- Confidence is separate from score and uses resolved/estimated item ratio, source quality, macro coverage, unresolved count, and completion state. Explicit or official values support stronger wording; fallback-heavy or incomplete data is presented as a reference value.
- Existing alcohol fields are only treated as a low-priority nutrition context. BodyOS does not infer alcohol calories, medical effects, or classify ordinary work drinks as alcohol; ambiguous alcohol detail is disclosed as a confidence limitation.
- Recommendation precedence is data reliability, calorie excess/deficit, protein deficiency, fat excess, vegetables/fiber, salt, then optimization. Actions are deterministic, non-contradictory, and capped at three.
- Previous-day comparison reports values and direction without calling every increase an improvement. Seven-day averages use only valid complete historical days, need two days to display, and use four days before strong trend wording.
- Rule traces keep the inputs, component result, and points for every score adjustment. This supports validation and a future optional LLM wording layer without giving that layer authority over nutrition data.
- If lookup is unresolved, ambiguous, variant-mismatched, or size-mismatched, it must not invent a trusted value; the existing dictionary/fallback path remains available.
- Dictionary-based calorie estimates should feel realistic, not perfectly precise.
- If only part of a meal is detected, unknown items should not silently become 0 kcal.
- Zero-meal text such as `なし`, `食べていない`, `未食`, `抜き`, `スキップ`, `朝食なし`, `昼食なし`, `夕食なし`, `晩御飯なし`, and `晩ご飯なし` is an explicit no-meal signal for breakfast, lunch, dinner, and snacks. It should return 0 kcal with no fallback estimate.
- Unknown non-empty meal text may still use fallback estimation.
- Manual user-entered calories are authoritative for that meal.

## Smart Food Capture Rules

- Food resolution priority is current explicit label, Personal confirmed Food Master, Official, Generic trusted source, then Estimate/Fallback.
- A user-confirmed label value is reusable active Personal Food knowledge. A weaker estimate must never replace it.
- Estimated and unknown values cannot be promoted by implicit save. Promotion requires the explicit「この食品の栄養値を今後も使用する」operation and `user_label` classification.
- Source presentation is deterministic: user label, Personal Master, and Official are High; trusted catalog is Medium; estimated and unknown are Low.
- Purchased quantity and consumed quantity are separate. Only consumed quantity contributes to Canonical meals, daily nutrition, Body Score, and Food Encounter persistence.
- Unknown consumed food has `calories_kcal=null`; it is never silently converted to 0 kcal. Known calories and unknown item count are displayed separately.
- Quantity scaling must respect nutrition basis and compatible units. Partial consumption of a `total` value that cannot be scaled remains review-required.
- Daily totals are recalculated from unique consumed FoodCandidate IDs. Editing item nutrition or consumed quantity changes totals; stored daily totals do not override the item sum.
- `canonical_builder_result()` is pure, emits Schema 1.0 directly, and must have zero Compatibility normalization changes before save.
- Source, confidence, and planned state are not new Canonical Schema fields. Source evidence belongs to Food Knowledge; only consumed food identity, quantity, nutrition, and explanatory notes enter the daily log.
- PR15 adds no database migration. Confirmed foods reuse existing normalized Food Knowledge tables; planned input remains Streamlit session state until consumed.

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

The function reads existing workout text fields such as `筋トレ内容`, `workout.menu`, and `workout_detail`. PR13 formally persists `構造化筋トレJSON` plus optional session/exercise/set counts while retaining the text compatibility field.

The result may include parsed exercises, PR candidates, next targets, progression context, confidence, and a short summary. Workout Intelligence remains unchanged; structured history is a persistence/display contract and does not add advanced analysis.

## PR13 Optional CSV Projection

The following optional columns are written only for new or explicitly updated records:

- `タンパク質(g)`, `脂質(g)`, `炭水化物(g)`
- `カロリー不明件数`
- `筋トレセッション数`, `筋トレ種目数`, `筋トレセット数`, `筋トレ時間(分)`
- `構造化食事JSON`, `構造化筋トレJSON`
- `Import ID`, `Import Schema Version`

Daily identity remains the calendar date in the current single-user CSV bridge. The formal future identity is owner plus date. Import conflict behavior is explicit: update supplied sections, replace the day, or skip the existing day.

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
