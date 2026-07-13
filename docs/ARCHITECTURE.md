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
- `dashboard.py`: Dashboard rendering layer for metrics, charts, normalized score component cards, improvement priorities, recent details, history tables, and Workout Intelligence display.
- `records.csv`: Current source of truth for user records.
- `food_dictionary.json`: General food calorie estimates.
- `brand_dictionary.json`: Brand and convenience food calorie estimates.
- `restaurant_dictionary.json`: Restaurant-specific calorie estimates.
- `bodyos_standard.py`: Reusable BodyOS Standard v1.0 rule engine for daily scoring and score component maximum-score metadata.
- `workout_intelligence.py`: Reusable Workout Intelligence v1 parser and training feedback engine.
- `README.md`: User-facing setup and feature documentation.
- `docs/`: Product, architecture, data, and development standards.

## Current Storage

The current storage model is CSV-first. Locally, records are saved to `records.csv`. In hosted usage, the app can persist `records.csv` through the GitHub Contents API.

## Current Data Flow

1. User records a day manually or pastes ChatGPT JSON.
2. Input is normalized into BodyOS columns.
3. Meals are parsed and calories are estimated unless explicit or manual calories are provided.
4. Workout fields are normalized for consistent training counts.
5. Workout Intelligence parses workout text for insights without changing the CSV schema.
6. Body Score is calculated by `calculate_bodyos_score(record)` in `bodyos_standard.py`.
7. Record is saved to CSV.
8. `app.py` passes normalized records to `dashboard.py`.
9. `dashboard.py` renders metrics, charts, normalized score component summaries, Workout Intelligence, and recent details.

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
