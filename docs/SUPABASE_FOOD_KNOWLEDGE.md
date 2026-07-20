# Food Knowledge Supabase Operations

## Scope

PR12 moves only Personal Food Master and Food Encounter persistence to Supabase. `records.csv`, JSON Import, Body Score, Workout Intelligence, and historical calories keep their existing contracts. The Resolver and Nutrition Intelligence still consume copied snapshots and never call Supabase.

## Schema Installation

Run [`supabase/migrations/20260720_food_knowledge.sql`](../supabase/migrations/20260720_food_knowledge.sql) in the Supabase SQL editor before enabling the repository. It creates:

- `foods`
- `food_aliases`
- `nutrition_sources`
- `nutrition_facts`
- `food_encounters`
- indexes, update triggers, RLS policies, and repository RPCs

`save_food_encounter_v1` locks one personal identity, checks `(owner_user_id, idempotency_key)`, saves the food and Encounter in one transaction, and increments usage only when the Encounter is new. Related aliases, sources, and facts use `ON DELETE CASCADE`; Encounter history keeps its row and sets `resolved_food_id` to null when a food is deleted. The application archives foods in normal operation instead of deleting them.

## Secrets

Copy the keys from [`.streamlit/secrets.example.toml`](../.streamlit/secrets.example.toml) into Streamlit Cloud Secrets or environment variables:

```toml
FOOD_KNOWLEDGE_REPOSITORY = "supabase"
FOOD_KNOWLEDGE_MODE = "fallback_json"
FOOD_KNOWLEDGE_USER_ID = "local-default"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "server-side secret"
SUPABASE_TIMEOUT_SECONDS = "8"
```

The service role key stays in the Streamlit server process. It is never rendered into HTML or logged. Do not put it in source control or browser-side code. The anon key is supported for future authenticated sessions, but the current single-user MVP needs the server-side service role because no Supabase Auth session exists yet.

Repository modes:

- `json_only`: never contacts Supabase.
- `fallback_json`: uses Supabase when healthy and switches to Local JSON for the rest of the process after a failure.
- `strict_supabase`: never writes fallback JSON. A failed connection returns empty Food Knowledge reads and disables Food Knowledge writes without stopping the app or `records.csv`.

`FOOD_KNOWLEDGE_REPOSITORY="json"` maps to `json_only`. `FOOD_KNOWLEDGE_REPOSITORY="supabase"` defaults to `fallback_json` unless `FOOD_KNOWLEDGE_MODE` is set.

## RLS And Ownership

Personal rows are keyed by explicit `owner_user_id`. RLS compares it with `auth.uid()::text`; shared and official foods are read-only for ordinary clients. The current server-side service role bypasses RLS, so `SupabaseFoodMasterRepository` adds an owner filter to every query and both RPCs validate the supplied owner.

When Supabase Auth is introduced, set `FOOD_KNOWLEDGE_USER_ID` from the authenticated `auth.uid()` and call the repository with the user JWT instead of the service key where practical. Do not accept an arbitrary owner ID from a client request.

## Migration

Dry-run is the default and succeeds when source files do not exist:

```bash
python3 scripts/migrate_food_knowledge_to_supabase.py
```

Apply after schema installation and service-role environment setup:

```bash
python3 scripts/migrate_food_knowledge_to_supabase.py --apply --report validation_artifacts/pr12-migration.json
```

The report includes source, before, after, malformed JSONL lines, duplicate skips, and errors. Food usage counts are copied from the master record; replayed Encounter rows do not increment them. Re-running the same migration upserts foods and skips duplicate idempotency keys. Keep `personal_food_master.json` and `food_encounters.jsonl` until post-cutover reconciliation is accepted.

## Rollback

1. Set `FOOD_KNOWLEDGE_REPOSITORY="json"` or `FOOD_KNOWLEDGE_MODE="json_only"` and redeploy.
2. Keep Supabase rows during the observation window. The retained JSON/JSONL files represent the pre-cutover state; export or reconcile any newer Supabase-only changes before making JSON authoritative again.
3. To delete one migrated owner after a verified backup, run the following in a transaction. Related aliases and nutrition rows cascade; Encounters are deleted explicitly.

```sql
begin;
delete from public.food_encounters where owner_user_id = 'local-default';
delete from public.foods where owner_user_id = 'local-default';
commit;
```

4. Use [`supabase/rollback/20260720_food_knowledge_rollback.sql`](../supabase/rollback/20260720_food_knowledge_rollback.sql) only when removing the complete PR12 schema for every owner.

## Failure Behavior

Missing secrets, invalid URL/key, timeout, network error, missing migration, and schema mismatch are converted to controlled repository errors. Logs contain exception types, not credentials. The Food Knowledge dashboard shows Storage, Connection, repository, last successful read/write, migration state, and unsynced fallback count.

In `fallback_json`, failover is intentionally sticky for the current process so a single save is not split across stores. New fallback writes are counted as unsynced, but automatic cloud reconciliation is not implemented. Operators must run migration/reconciliation after Supabase recovery. `records.csv` persistence is an independent path and remains available.

## Hosted Verification Checklist

1. Apply the migration and configure Streamlit Cloud Secrets.
2. Confirm `Storage = Supabase` and `Connection = Connected`.
3. Save one new meal, retry the same save, and confirm one Encounter and one usage increment.
4. Restart/redeploy Streamlit and confirm the food and Encounter remain.
5. Temporarily use an invalid key in a test deployment and confirm the dashboard still loads and reports Error/Fallback.
6. Re-run JSON import and confirm Duplicate skipped increases without a duplicate row.

Hosted persistence cannot be claimed from local fake-service validation alone. Record the project/deployment and timestamp when this checklist is performed.
