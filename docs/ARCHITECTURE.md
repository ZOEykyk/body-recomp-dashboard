# Architecture

## Current Architecture

BodyOS currently uses a Streamlit-first architecture. This is appropriate for the foundation phase because it keeps iteration fast, makes local validation simple, and preserves a small operational surface.

```text
User
↓
ChatGPT coaching conversation
↓
JSON log
↓
Streamlit JSON import
↓
Normalizer
↓
Food Parser
↓
Food Resolver / Source Policy
↓
Workout normalizer
↓
Workout Intelligence
↓
CSV storage
↓
Dashboard renderer
↓
BodyOS Standard rule engine
↓
Body Score / Coach feedback
```

## Main Components

- `app.py`: Streamlit page setup, input forms, JSON import flow, normalization, CSV persistence, GitHub-backed storage, and high-level orchestration.
- `dashboard.py`: Dashboard rendering layer for the Dashboard v1.0 information hierarchy, metrics, core trend charts, normalized score component cards, improvement priorities, recent details, history tables, and Workout Intelligence display.
- `records.csv`: Current source of truth for user records.
- `food_dictionary.json`: General food calorie estimates.
- `brand_dictionary.json`: Brand and convenience food calorie estimates.
- `restaurant_dictionary.json`: Restaurant-specific calorie estimates.
- `food_parser.py`: Pure food text parser that converts meal free text into structured food items and explicit nutrition values without owning nutrition lookup data.
- `food_aliases.py`: Lightweight alias normalization for parser output. It does not store calorie or macro values.
- `food_lookup.py`: Pure local Food Lookup Engine that resolves parsed foods against the reviewed seed catalog and returns nutrition, source, and match metadata.
- `food_lookup_catalog.json`: Small reviewed catalog of official product/menu nutrition facts. It is local data, not a runtime web fetch or a broad Food Master database.
- `food_knowledge_catalog.py`: Adapter that exposes the existing calorie dictionaries through one generic-catalog contract.
- `food_resolver.py`: Pure application-level Single Source of Truth for candidate collection, source selection, quantity-aware nutrition, fallback, confidence, and resolution counts.
- `food_source_models.py`: One shared metadata contract for every nutrition source.
- `food_source_policy.py`: Pure deterministic product-tier and source-level priority, freshness, validity, and conflict-resolution policy.
- `food_master_models.py`: Personal Food Master record and encounter contracts.
- `food_master_repository.py`: Storage-neutral Repository interface, query defaults, idempotent save unit, and local JSON/JSONL adapter.
- `supabase_food_master_repository.py`: Supabase/PostgREST adapter that maps normalized tables back to the existing domain model and uses an atomic Encounter RPC.
- `food_repository_factory.py`: `json_only`, `fallback_json`, and `strict_supabase` repository selection and startup-safe failure handling.
- `personal_food_master.py`: Personal identity resolution, candidate creation, promotion, usage tracking, and encounter logging.
- `food_knowledge_dashboard.py`: Read-only Food Knowledge growth metrics and responsive Streamlit projection.
- `nutrition_targets.py`: Centralized, profile-safe target defaults and formulas.
- `nutrition_intelligence.py`: Pure deterministic Nutrition Intelligence aggregation, scoring, comparisons, and rule trace.
- `nutrition_rules.py`: Centralized Japanese coaching templates, heuristics, and recommendation precedence.
- `bodyos_standard.py`: Reusable BodyOS Standard v1.0 rule engine for daily scoring and score component maximum-score metadata.
- `workout_intelligence.py`: Reusable Workout Intelligence v1 parser and training feedback engine.
- `README.md`: User-facing setup and feature documentation.
- `docs/`: Product, architecture, data, and development standards.

## Current Storage

Daily records remain CSV-first. Locally, records are saved to `records.csv`; hosted usage can persist that file through the GitHub Contents API. Food Knowledge is a separate bounded context: Personal foods, aliases, nutrition sources/facts, and Encounters can use Supabase while the JSON/JSONL adapter remains available for fallback and rollback.

## Current Data Flow

1. User records a day manually or pastes ChatGPT JSON.
2. Input is normalized into BodyOS columns.
3. Meals are parsed by `parse_food_text(text, meal_type)` into structured food items and explicit nutrition values.
4. Food Resolver collects Explicit, Personal, Official, Generic, and Fallback candidates before the shared Source Policy selects nutrition.
5. Workout fields are normalized for consistent training counts.
6. Workout Intelligence parses workout text for insights without changing the CSV schema.
7. Body Score is calculated by `calculate_bodyos_score(record)` in `bodyos_standard.py`.
8. Record is saved to CSV.
9. `app.py` passes normalized records to `dashboard.py`.
10. `dashboard.py` renders the dashboard and passes a read-only Food Knowledge snapshot to Nutrition Intelligence.
11. `food_knowledge_dashboard.py` renders Food Knowledge counts, confidence, usage, and recent activity without changing the CSV.

## Nutrition Parser Layer

PR8.1 introduces a parser-first nutrition architecture:

```text
Meal text
↓
food_parser.py
↓
structured parsed foods / explicit kcal and PFC
↓
food_resolver.py / all candidates
↓
food_source_policy.py
↓
nutrition resolution
```

The parser understands text structure and does not own nutrition. `food_lookup.py` remains the lower-level official-catalog adapter. Application consumers call `food_resolver.py`, which collects every candidate before `food_source_policy.py` applies the fixed order Explicit, Personal, Official, Generic, and Fallback. Source validity, freshness, verification, and same-tier conflicts are evaluated centrally.

PR9 adds a Personal Food Master before seed lookup. It separates append-only food encounters from reusable food records, aliases, source candidates, and usage statistics. Unknown or estimated encounters remain candidates; only reviewed candidates or foods supported by a sufficiently authoritative source become active. PR12 adds a normalized Supabase adapter without changing the Resolver or intelligence interfaces. JSON/JSONL remains available; GitHub persistence still applies only to `records.csv`.

Personal Food Master encounter writes are idempotent. A stable fingerprint includes owner, date, meal type, normalized fragment, save/import identity, and a normalized meal-content hash. Supabase enforces the key with a unique constraint and saves the Encounter plus usage increment in one RPC transaction. It prevents retries or repeated imports from incrementing usage more than once, while changed content or quantity on the same date becomes a new encounter. The compact management UI remains isolated and works only through `FoodMasterRepository`.

Supabase writes from ordinary authenticated roles are RPC-only. The normalized schema ties aliases to both food and owner, and keys nutrition sources by food plus source ID so repeated domain identifiers remain valid without cross-food joins. Startup health requires schema version `20260720.2`; a partial or stale schema is treated as unavailable.

Nutrition Intelligence is a separate read-time layer after nutrition resolution. `dashboard.py` calls the pure `analyze_nutrition(record, history, profile, now, food_knowledge)` interface. The engine passes the copied snapshot to the shared Resolver and has no Streamlit, file, network, repository, or LLM dependency.

See [Food Knowledge Foundation](FOOD_KNOWLEDGE.md) for resolver contracts and [Food Knowledge Supabase Operations](SUPABASE_FOOD_KNOWLEDGE.md) for schema, RLS, migration, rollback, and failure handling.

## Dashboard Layer

The dashboard layer is intentionally separated from app orchestration:

```text
app.py
↓
dashboard.py
↓
bodyos_standard.py / workout_intelligence.py
```

- `app.py` orchestrates page setup, data loading, data saving, imports, and user input.
- `dashboard.py` renders visual summaries and calls stable analysis interfaces. It derives component achievement percentages at render time and does not change stored raw scores.
- `bodyos_standard.py` evaluates daily BodyOS scores and exposes shared component maximum scores through `SCORE_COMPONENT_MAXIMA`.
- `workout_intelligence.py` analyzes workout detail text.

This separation keeps future intelligence work safer by allowing scoring and workout analysis to evolve behind stable interfaces while the Streamlit app remains a thin coordinator.

## Dashboard v1.0 Information Hierarchy

Dashboard v1.0 is organized for quick daily interpretation:

1. Body Score summary.
2. Today's metrics.
3. Workout Intelligence Top 3 recommendations.
4. Core trend charts: Body Score, weight, calories, and steps.
5. History.
6. Detailed analysis, including score components and recent details.

Low-value or overly specific charts are intentionally excluded from the primary dashboard. This keeps the page focused without changing stored records, Body Score rules, Workout Intelligence logic, CSV schema, or JSON import behavior.

## Future Architecture

Future platform phases may split BodyOS into:

- React / Next.js frontend.
- FastAPI backend.
- Supabase or database storage.
- AI Coach Engine.
- Workout Intelligence.
- Nutrition Intelligence.

## Migration Principle

Do not migrate away from Streamlit until the product standards, data contracts, and scoring semantics are stable enough to justify a platform split. Streamlit remains the correct foundation-phase implementation.
