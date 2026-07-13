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
Food parser / calorie estimator
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
- `bodyos_standard.py`: Reusable BodyOS Standard v1.0 rule engine for daily scoring and score component maximum-score metadata.
- `workout_intelligence.py`: Reusable Workout Intelligence v1 parser and training feedback engine.
- `README.md`: User-facing setup and feature documentation.
- `docs/`: Product, architecture, data, and development standards.

## Current Storage

The current storage model is CSV-first. Locally, records are saved to `records.csv`. In hosted usage, the app can persist `records.csv` through the GitHub Contents API.

## Current Data Flow

1. User records a day manually or pastes ChatGPT JSON.
2. Input is normalized into BodyOS columns.
3. Meals are parsed by `parse_food_text(text, meal_type)` into structured food items and explicit nutrition values.
4. Calories are estimated from explicit kcal first, then Food Lookup, then dictionary matching, then fallback estimation unless manual calories are provided.
5. Workout fields are normalized for consistent training counts.
6. Workout Intelligence parses workout text for insights without changing the CSV schema.
7. Body Score is calculated by `calculate_bodyos_score(record)` in `bodyos_standard.py`.
8. Record is saved to CSV.
9. `app.py` passes normalized records to `dashboard.py`.
10. `dashboard.py` renders the dashboard in priority order: Body Score, today's metrics, Workout Intelligence, core trend charts, history, and detailed analysis.

## Nutrition Parser Layer

PR8.1 introduces a parser-first nutrition architecture:

```text
Meal text
↓
food_parser.py
↓
structured parsed foods / explicit kcal and PFC
↓
food_lookup.py / reviewed seed catalog
↓
existing dictionary and fallback calorie estimator
```

The parser understands text structure: delimiters, composite meals, brand context, variants, size, quantities, no-meal text, and explicit nutrition such as `223kcal、P12g、F15g、C14g`. It returns food item contracts designed for lookup (`brand`, `canonical_name`, `variant`, `size`, `quantity`, `unit`, `original_fragment`, `resolution`, `confidence`, `needs_review`, and `explicit_nutrition`). `food_lookup.py` is a separate pure layer: it uses the reviewed local catalog, returns `status`, `match_type`, `confidence`, `needs_review`, `candidates`, original parsed identity, `nutrition`, and `source` metadata. It requires brand agreement whenever the parser supplies a brand, declines ambiguous matches, and exposes `calculate_lookup_total()` for basis-aware totals. Explicit values from the user remain highest priority. Broad Food Master ingestion and runtime public-data fetching remain future work.

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
