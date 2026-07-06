# Architecture

## Current Architecture

BodyOS currently uses a Streamlit single-app architecture. This is appropriate for the foundation phase because it keeps iteration fast, makes local validation simple, and preserves a small operational surface.

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
CSV storage
↓
Dashboard
↓
Body Score / Coach feedback
```

## Main Components

- `app.py`: Streamlit UI, import flow, normalization, scoring, charts, CSV persistence, and GitHub-backed storage.
- `records.csv`: Current source of truth for user records.
- `food_dictionary.json`: General food calorie estimates.
- `brand_dictionary.json`: Brand and convenience food calorie estimates.
- `restaurant_dictionary.json`: Restaurant-specific calorie estimates.
- `README.md`: User-facing setup and feature documentation.
- `docs/`: Product, architecture, data, and development standards.

## Current Storage

The current storage model is CSV-first. Locally, records are saved to `records.csv`. In hosted usage, the app can persist `records.csv` through the GitHub Contents API.

## Current Data Flow

1. User records a day manually or pastes ChatGPT JSON.
2. Input is normalized into BodyOS columns.
3. Meals are parsed and calories are estimated unless explicit or manual calories are provided.
4. Workout fields are normalized for consistent training counts.
5. Body Score is calculated from current rules.
6. Record is saved to CSV.
7. Dashboard reads normalized records and renders metrics, charts, and recent details.

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
