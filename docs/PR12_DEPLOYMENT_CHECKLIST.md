# PR12 Deployment Checklist

## Gate

PR12 is not releasable until every required item is checked and `PR12_ACCEPTANCE_TEST.md` is fully PASS. Current hosted status: **NOT RUN**.

## Supabase Project

- [ ] Project owner, project ref, region, plan, and environment are recorded.
- [ ] Staging is used for strict/fallback failure tests.
- [ ] Backup availability and retention for the selected plan are confirmed.
- [ ] A logical pre-release backup exists outside the project.
- [ ] Migration history is clean: `supabase migration list`.
- [ ] `supabase db push --dry-run` shows only the reviewed migration.
- [ ] Migration applied from Git, not recreated in Table Editor.
- [ ] `food_knowledge_schema_version_v1()` returns `20260720.2`.
- [ ] All five Food Knowledge tables have RLS enabled.
- [ ] Authenticated/anon roles have no direct table write privilege.
- [ ] Service-role key is stored only in server-side secret management.

Run `supabase/verification/pr12_acceptance.sql` in the SQL editor and save the read-only output as evidence.

## Table State

Official catalog records remain in the reviewed local catalog in PR12; they are not automatically copied into these tables.

| Table | Fresh schema | After one automated fixture | Normal production state |
|---|---:|---:|---|
| `foods` | 0 | 1 | One row per non-duplicate Personal identity; archived rows may remain |
| `food_aliases` | 0 | at least 1 | Every alias references a food with the same owner |
| `nutrition_sources` | 0 | 1 | Zero or more per food; `(food_id, source_id)` is unique |
| `nutrition_facts` | 0 | 1 | Each row references a source belonging to the same food |
| `food_encounters` | 0 | 1 | One row per owner/idempotency key |

After JSON/JSONL migration:

- [ ] `foods` count is reconciled to source Food Master rows for the owner.
- [ ] `food_encounters` count equals valid source Encounter rows after duplicate/error adjustments.
- [ ] Alias count equals distinct `(food_id, normalized_alias)` values.
- [ ] Nutrition source/fact counts equal nested source/fact records; candidate-only foods may legitimately have zero.
- [ ] Duplicate identity, duplicate idempotency, count mismatch, and orphan queries return zero rows.

## Streamlit Cloud Secrets

- [ ] `FOOD_KNOWLEDGE_REPOSITORY = "supabase"`
- [ ] `FOOD_KNOWLEDGE_MODE = "strict_supabase"` for production.
- [ ] `FOOD_KNOWLEDGE_USER_ID` matches the migrated owner and remains stable.
- [ ] `SUPABASE_URL` belongs to the intended environment.
- [ ] `SUPABASE_SECRET_KEY` is present and not displayed or logged; legacy `SUPABASE_SERVICE_ROLE_KEY` is used only during transition.
- [ ] `SUPABASE_TIMEOUT_SECONDS = "8"` initially.
- [ ] Existing GitHub/records settings are unchanged.
- [ ] No real `.streamlit/secrets.toml` is committed.

## Streamlit Cloud Smoke Test

- [ ] Deploy the reviewed commit SHA.
- [ ] App opens without ImportError.
- [ ] Cloud logs contain no secret and no repository traceback.
- [ ] Food Knowledge shows `Storage = Supabase`.
- [ ] Connection shows `Connected`.
- [ ] Repository shows `SupabaseFoodMasterRepository`.
- [ ] Migration shows `20260720.2`.
- [ ] Last Read updates after dashboard load.
- [ ] Food Resolver resolves known Personal and Official examples as before.
- [ ] New Personal Food appears in Supabase and dashboard.
- [ ] New Encounter appears exactly once.
- [ ] Exact retry increments Duplicate skipped but not `usage_count`.
- [ ] JSON Import reports Personal, Official, Fallback, saved, duplicate, and failed counts.
- [ ] Reboot/redeploy preserves Food Knowledge and counts.
- [ ] Desktop and mobile layouts have no exception or horizontal overflow.

## Failure Drills

- [ ] In staging, strict mode with invalid connectivity starts BodyOS but stops Food Knowledge writes and shows Error.
- [ ] In staging, fallback mode writes JSON once, shows Fallback/warning, and increments unsynced count.
- [ ] Recovery from fallback includes exporting local files before reboot and explicit reconciliation.
- [ ] Rotating a service key and rebooting restores Connected state.

## Compatibility

- [ ] PR8.1, PR8.2, PR8.3, PR9, PR10, PR11, and PR12 validations pass.
- [ ] `python3 -c "import app; print('app import ok')"` passes with configured and missing Secrets.
- [ ] JSON Import schema is unchanged.
- [ ] Workout Intelligence files and behavior are unchanged.
- [ ] `records.csv` is byte-identical to `origin/main`.

## Release Decision

- [ ] Migration operator signs off.
- [ ] Backup/restore operator signs off.
- [ ] PM signs off on all Acceptance evidence.
- [ ] PR changes from Draft to Ready for Review only after all above requirements pass.
