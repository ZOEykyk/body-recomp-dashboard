# Food Knowledge Production Runbook

## Current Environment Decision

As of 2026-07-20, no Supabase project reference or credential is present in the local environment, repository files, GitHub Actions secrets, or GitHub repository variables. Opening the Supabase Projects dashboard redirected to sign-in, so no organization/project inventory was accessible. Streamlit Cloud is also not connected to this workspace. An existing project is therefore **unconfirmed**; a project owner must identify it or create a dedicated BodyOS project before acceptance can run.

PR12 owns only Food Knowledge. It does not migrate `records.csv`, workouts, images, or authentication.

## Required Supabase Project

Use one staging project for destructive acceptance tests and one production project when practical. Record:

- organization and project name
- project ref and region
- project URL
- database plan and backup capability
- database owner/operator
- Streamlit staging and production app URLs
- stable single-user owner ID, currently `local-default`

Choose the region deliberately because changing a Supabase project region requires creating and migrating to another project. Apply schema changes through committed migration files and one designated operator; Supabase recommends migration history plus `db push` instead of untracked remote edits.

Official references:

- [Supabase database migrations](https://supabase.com/docs/guides/deployment/database-migrations)
- [Supabase CLI db push](https://supabase.com/docs/reference/cli/v1/supabase-db-push)
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase backups](https://supabase.com/docs/guides/platform/backups)
- [Streamlit Community Cloud secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
- [Streamlit reboot procedure](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/reboot-your-app)

## Streamlit Cloud Configuration

Set these in the app's Advanced settings / Secrets field. Never commit the real `secrets.toml`.

```toml
FOOD_KNOWLEDGE_REPOSITORY = "supabase"
FOOD_KNOWLEDGE_MODE = "strict_supabase"
FOOD_KNOWLEDGE_USER_ID = "local-default"
SUPABASE_URL = "https://<project-ref>.supabase.co"
SUPABASE_SECRET_KEY = "<sb_secret_server-only-key>"
SUPABASE_TIMEOUT_SECONDS = "8"
```

Required:

| Setting | Purpose | Production rule |
|---|---|---|
| `FOOD_KNOWLEDGE_REPOSITORY` | Select adapter | `supabase` |
| `FOOD_KNOWLEDGE_MODE` | Failure policy | `strict_supabase` recommended |
| `FOOD_KNOWLEDGE_USER_ID` | Stable owner boundary | Never change after cutover without migration |
| `SUPABASE_URL` | Project REST endpoint | Project-specific secret/config |
| `SUPABASE_SECRET_KEY` | Recommended server-only privileged access | Never expose in browser, logs, or Git |
| `SUPABASE_TIMEOUT_SECONDS` | Network timeout | `8` initially |

Legacy compatibility: `SUPABASE_SERVICE_ROLE_KEY`. Optional/currently unused client settings: `SUPABASE_PUBLISHABLE_KEY` and `SUPABASE_ANON_KEY`. Publishable/anon credentials are not sufficient for the current privileged single-user write path.

Supabase recommends `sb_secret_...` for new server components and plans to deprecate legacy JWT API keys by the end of 2026. BodyOS sends a new secret key only in the `apikey` header; legacy JWT keys also use the Bearer header. See [Understanding API keys](https://supabase.com/docs/guides/getting-started/api-keys).

Existing `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `RECORDS_CSV_BRANCH`, and `RECORDS_CSV_PATH` remain independent and are not replaced by Supabase.

For local operation, the same names may be environment variables or ignored `.streamlit/secrets.toml` entries. Restart Streamlit after changing local secrets.

## Initial Build And Migration

1. Identify or create staging and production projects.
2. Install and authenticate the Supabase CLI, then link only the intended project.
3. Confirm migration history before writing:

```bash
supabase link --project-ref <project-ref>
supabase migration list
supabase db push --dry-run
```

4. Apply `supabase/migrations/20260720_food_knowledge.sql` through `supabase db push`. Do not make a parallel Table Editor change.
5. Confirm the health RPC returns `20260720.2` and run the schema checks from `PR12_DEPLOYMENT_CHECKLIST.md`.
6. Run the real-Supabase acceptance seed in staging.
7. Dry-run legacy data migration:

```bash
python3 scripts/migrate_food_knowledge_to_supabase.py --report validation_artifacts/pr12-migration-dry-run.json
```

8. Back up JSON/JSONL and Supabase, then apply:

```bash
python3 scripts/migrate_food_knowledge_to_supabase.py --apply --report validation_artifacts/pr12-migration-apply.json
```

9. Re-run apply once. Expected: no extra Encounter and only duplicate skips.
10. Keep `personal_food_master.json`, `food_encounters.jsonl`, reports, hashes, and row-count evidence through the rollback window.

## Production Deployment

1. Freeze Food Knowledge edits and capture baseline counts.
2. Confirm current backups and the rollback owner.
3. Apply and verify the database migration before enabling the app adapter.
4. Configure Streamlit Secrets with `strict_supabase`.
5. Deploy the exact reviewed commit.
6. Confirm Cloud logs contain no ImportError or secret value.
7. Confirm Food Knowledge shows Supabase, Connected, and Migration `20260720.2`.
8. Run AT-01 through AT-04 with disposable data.
9. Reboot/redeploy and complete AT-05.
10. Run staging-only AT-06 and AT-07.
11. Confirm AT-08 and lift the edit freeze.

## Repository Switching

- `strict_supabase`: production default. A Supabase fault stops Food Knowledge writes and avoids silent split-brain storage while the rest of BodyOS can start.
- `fallback_json`: emergency/staging mode. It keeps Food Knowledge writable but creates unsynced local data that Streamlit Cloud may discard.
- `json_only`: rollback/local mode. It never contacts Supabase.

Changing mode requires updating Streamlit Secrets and rebooting the app. Record the old/new mode, operator, time, reason, and authoritative store.

## Backup Policy

Before migration, deployment, rollback, or destructive acceptance:

1. Copy and hash `personal_food_master.json` and `food_encounters.jsonl` if present.
2. Capture per-table and per-owner counts.
3. Create a logical Supabase backup using `supabase db dump` or `pg_dump` and store it off-project with restricted access.
4. Verify the project's Dashboard backup status under Database > Backups. Supabase documents automatic daily backups for paid plans and recommends regular logical exports for free-tier projects.
5. Record backup location, timestamp, project ref, commit, schema version, and a restore owner.

Recommended minimum for this MVP: logical export before every release plus weekly off-project retention. Treat provider backup availability and retention as **unconfirmed** until the selected project plan is recorded. A backup is not accepted until a restore drill succeeds in a non-production project.

## Rollback

Application rollback is preferred over destructive schema rollback:

1. Freeze Food Knowledge writes.
2. Export all Supabase Food Knowledge created since cutover.
3. Choose one authoritative store; do not switch blindly if fallback writes exist.
4. Set `FOOD_KNOWLEDGE_MODE = "json_only"` and `FOOD_KNOWLEDGE_REPOSITORY = "json"`.
5. Restore/reconcile JSON/JSONL, reboot Streamlit, and verify Resolver and dashboard behavior.
6. Keep Supabase tables intact during the observation window.

Only after backup and approval, remove test-owner rows or execute `supabase/rollback/20260720_food_knowledge_rollback.sql`. That script removes the entire Food Knowledge schema and is not a routine application rollback.

## Incident Recovery

| Symptom | Immediate action | Recovery |
|---|---|---|
| Connection Error in strict mode | Keep app up; stop Food Knowledge writes | Validate URL/key, schema health RPC, network, and project status; reboot after correction |
| Fallback warning | Record start time and unsynced count | Restore Supabase, export fallback files before restart, migrate/reconcile once, then return to strict mode |
| Duplicate Encounter suspected | Freeze retries for that operation | Query owner/idempotency duplicates and compare usage count; do not edit counts without backup |
| Schema mismatch | Keep strict mode | Compare migration history, apply reviewed pending migration, then health-check |
| Partial/corrupt data | Freeze Food Knowledge writes | Restore into staging first, reconcile counts, then schedule production restore and downtime |
| Service key exposure | Revoke/rotate immediately | Update Streamlit Secret, reboot, inspect access logs, and document incident |

## Operational Ownership

Before release, name one migration operator, one backup/restore operator, and one PM approver. PR12 must remain Draft while the Supabase project, backup behavior, or Streamlit restart persistence is unverified.
