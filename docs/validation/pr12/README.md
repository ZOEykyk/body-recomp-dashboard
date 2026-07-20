# PR12 UI Validation

Validated the actual local Streamlit app on 2026-07-20 with the repository in `json_only` mode because this workspace has no Supabase project credentials.

## Captures

- `food-knowledge-storage-desktop-1280.png`: desktop viewport, 1280 x 800.
- `food-knowledge-storage-mobile-390.png`: mobile viewport, 390 x 780.

The captures confirm that Storage, Connection, repository implementation, last read/write, and unsynced count are visible. At 390px the cards stack to one column, the timestamp remains readable, and the document width equals the viewport width (`scrollWidth = clientWidth = 390`), so no horizontal overflow is present.

## Scope

- Actual Streamlit render: confirmed locally.
- Local JSON mode and durability warning: confirmed.
- Streamlit exception: none observed.
- Hosted Supabase persistence and Streamlit Cloud restart: not run because no project URL or secret/service-role credential is available in this workspace. Follow `docs/SUPABASE_FOOD_KNOWLEDGE.md` after deployment.
