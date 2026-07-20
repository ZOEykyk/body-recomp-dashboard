# PR12 Acceptance Test

## Status

Created on 2026-07-20. The local environment has no `SUPABASE_URL`, secret/service-role key, repository setting, local `secrets.toml`, GitHub Actions secret, or repository variable. The Supabase Projects dashboard redirected to sign-in, so no project inventory was accessible. A BodyOS Supabase project could not be identified. Therefore every hosted case below is **NOT RUN** until a project owner supplies the project and Streamlit Cloud deployment.

Do not mark PR12 Ready for Review until AT-01 through AT-08 have evidence and pass. Run destructive/failure cases against a staging deployment, not the production app.

## Preconditions

- A dedicated Supabase project or isolated staging project exists in the same preferred region as the app's users.
- `supabase/migrations/20260720_food_knowledge.sql` is applied and `food_knowledge_schema_version_v1()` returns `20260720.2`.
- Streamlit Cloud Secrets use a stable `FOOD_KNOWLEDGE_USER_ID`.
- The pre-deployment JSON/JSONL files and Supabase database are backed up.
- The operator records project ref, Streamlit app URL, commit SHA, UTC timestamps, row counts, screenshots, and Cloud log excerpts without secret values.

## Automated Real-Supabase Fixture

The script writes only to an isolated owner prefixed `pr12-acceptance-`.

```bash
export SUPABASE_URL="https://<project-ref>.supabase.co"
export SUPABASE_SECRET_KEY="<sb_secret_server-only-key>"
python3 scripts/acceptance_pr12_supabase.py --phase seed --confirm-write
```

The seed phase verifies Personal Food, alias, nutrition source/fact, Encounter persistence, a new repository process, duplicate suppression, and unchanged `usage_count`. Keep `validation_artifacts/pr12-acceptance-state.json` for post-restart verification:

```bash
python3 scripts/acceptance_pr12_supabase.py --phase verify
```

After evidence is accepted, remove only the isolated fixture:

```bash
python3 scripts/acceptance_pr12_supabase.py --phase cleanup --confirm-write
```

## Test Cases

### AT-01 Personal Food Survives Restart

1. Run the seed phase and record `food_id`, owner, and count.
2. Stop the local Streamlit process or reboot the staging Streamlit app.
3. Run the verify phase with the same state file.
4. Open Food Knowledge and Personal Food Master using the fixture owner if UI evidence is required.

Expected: the same food remains, its alias and nutrition data round-trip, and `usage_count = 1`.

### AT-02 Encounter Survives Restart

1. Complete AT-01.
2. Query `food_encounters` by the recorded owner and `idempotency_key` before and after restart.

Expected: exactly one row remains with the same `encounter_id`, parsed identity, nutrition provenance, and resolved food.

### AT-03 JSON Import End To End

1. Record baseline row counts for the production owner.
2. Import one schema-compatible JSON record containing one known official food and one new personal food.
3. Confirm Import Summary shows resolution origins plus Encounter saved, Duplicate skipped, and Save failed.
4. Confirm the Food Knowledge dashboard and Personal Food Master reflect the new records.
5. Query Supabase using the checks in `PR12_DEPLOYMENT_CHECKLIST.md`.

Expected: the shared Food Resolver is used; new Food Knowledge and Encounters are stored in Supabase; `Save failed = 0`; no CSV/JSON import schema change occurs.

### AT-04 Idempotent Encounter And Usage Count

1. Capture Encounter count and food `usage_count`.
2. Retry the exact same save/import operation.
3. Capture both values again.

Expected: Encounter count is unchanged, `usage_count` is unchanged, and Duplicate skipped increases. The automated seed phase covers the RPC-level case.

### AT-05 Streamlit Cloud Redeploy Durability

1. Complete AT-03 in the staging deployment.
2. Save screenshots and Supabase counts.
3. Reboot or redeploy the app from Streamlit Community Cloud.
4. Re-open Food Knowledge and repeat the Supabase queries.

Expected: all Food Knowledge remains, Storage is Supabase, Connection is Connected, Migration is `20260720.2`, and counts match the pre-redeploy evidence.

### AT-06 strict_supabase Failure

1. In staging, set `FOOD_KNOWLEDGE_MODE = "strict_supabase"` and temporarily use an invalid URL or key.
2. Reboot the app and inspect Cloud logs and UI.
3. Attempt a Food Knowledge save without changing a real daily record.

Expected: the app still starts; Food Knowledge reports Error; Food Knowledge writes stop with a visible failure; no fallback JSON is written; `records.csv` handling remains independent; no credential appears in logs.

### AT-07 fallback_json Failure

1. In staging, set `FOOD_KNOWLEDGE_MODE = "fallback_json"` and temporarily make Supabase unreachable.
2. Reboot and save one disposable meal.
3. Inspect UI, logs, local JSON/JSONL, and unsynced count.

Expected: the app starts, Connection is Fallback, a warning explains split-storage risk, the Encounter is written to JSON once, and unsynced count increases. Because Streamlit Cloud local files are not durable, this mode is not the recommended steady production mode.

### AT-08 records.csv Integrity

Run before and after every acceptance session:

```bash
git diff --exit-code origin/main -- records.csv
git show origin/main:records.csv | shasum
shasum records.csv
```

Expected: no diff and matching hashes. Do not use a test that saves disposable daily records into the production `records.csv`.

## Acceptance Record

| Test | Status | Evidence | Operator / UTC |
|---|---|---|---|
| AT-01 Personal Food restart | NOT RUN | Supabase project unavailable | — |
| AT-02 Encounter restart | NOT RUN | Supabase project unavailable | — |
| AT-03 JSON Import E2E | NOT RUN | Streamlit Cloud access unavailable | — |
| AT-04 Idempotency | NOT RUN in real Supabase; local adapter test passed | Add SQL counts and script output | — |
| AT-05 Redeploy durability | NOT RUN | Streamlit Cloud access unavailable | — |
| AT-06 strict failure | NOT RUN hosted; local startup test passed | Add UI/log evidence | — |
| AT-07 fallback failure | NOT RUN hosted; local startup test passed | Add UI/log evidence | — |
| AT-08 records.csv | PASS locally | Byte comparison against `origin/main` | Codex / 2026-07-20 |

## Exit Criteria

- All eight rows are PASS with dated evidence.
- No unresolved Sev-1 or Sev-2 data-integrity issue remains.
- Backup and rollback have named operators.
- PR12 remains Draft while any hosted persistence, redeploy, or failure-mode case is NOT RUN.
