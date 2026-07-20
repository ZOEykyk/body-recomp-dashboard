# PR12 Migration Review

Reviewed on 2026-07-20 against the PR11 domain contracts. Static review is complete. Execution against real PostgreSQL/Supabase is **NOT RUN** because no project or credential is available.

## Findings Resolved

1. `source_id` could not safely be globally unique because the existing source contract reuses IDs such as `explicit-user-label`. `nutrition_sources` now uses `(food_id, source_id)` as its primary key, nutrition facts use a matching composite foreign key, and repository hydration joins by both fields.
2. Alias ownership could differ from the referenced food. `food_aliases(food_id, owner_user_id)` now references the same composite key in `foods`.
3. Direct authenticated table writes could bypass RPC validation. Anon/authenticated roles are read-only; writes go through owner-validating security-definer RPCs. Service-role direct writes remain for the controlled migration script.
4. Authenticated callers could attempt shared/official writes. Non-service RPC calls are restricted to `scope = personal`.
5. A reused `food_id` could target another owner. The RPC rejects cross-owner ID collisions.
6. Partial/incorrect schema detection previously checked only one table. The repository now requires `food_knowledge_schema_version_v1() = 20260720.2` at startup.
7. Missing value checks allowed empty IDs, identities, aliases, names, meal types, and fragments. Required fields and positive quantities now have database checks.
8. `use_count` and `usage_count` could drift. The schema requires equality and the Encounter RPC changes both in the same transaction.
9. Legacy JSON may contain mismatched count aliases. The Supabase adapter normalizes both to the same non-negative maximum before migration.

## Constraint Review

| Area | Decision | Result |
|---|---|---|
| Primary keys | Domain IDs remain text; nutrition source identity is food-scoped | Reviewed |
| Foreign keys | Alias owner is tied to food owner; facts tie to the exact food/source pair | Reviewed |
| Unique constraints | Personal active identity and owner/idempotency are unique | Reviewed |
| Indexes | Owner/status, owner/usage, owner/update, alias lookup, food source/fact, encounter date/food | Reviewed |
| RLS | Enabled on all five tables; owner/private reads and shared reads are explicit | Reviewed statically |
| Write privilege | RPC-only for anon/authenticated; service role retained for server migration | Reviewed statically |
| Delete policy | Alias/source/fact cascade; Encounter keeps provenance row and nulls resolved food | Reviewed |
| Defaults | status/review/count/JSON/timestamps/schema defaults are deterministic | Reviewed |
| Timestamps | UTC-capable `timestamptz`; update triggers cover mutable tables | Reviewed |
| NULL constraints | Identity and Encounter core fields required; optional provenance/nutrition remains nullable | Reviewed |

## Table Decisions

### foods

- `food_id` is the domain-generated primary key.
- `(food_id, owner_user_id)` is additionally unique for composite ownership references.
- `(owner_user_id, identity_key)` is unique for non-archived personal foods.
- `canonical_name`, `identity_key`, owner, scope, status, review status, counts, timestamps, and schema version are constrained.
- `use_count` is retained for backward compatibility, but must equal `usage_count`.

### food_aliases

- Alias IDs are deterministic in the RPC.
- `(food_id, normalized_alias)` prevents duplicate aliases on one food.
- The composite foreign key prevents a row owned by user A from pointing at user B's food.
- Multiple foods may intentionally share an alias so ambiguity remains reviewable.

### nutrition_sources

- Primary key is `(food_id, source_id)`, matching the existing nested domain model.
- Validity windows, verification status, and confidence are constrained.
- Deleting a food cascades to its sources.

### nutrition_facts

- Each fact references `(food_id, source_id)` and cannot attach to another food's source.
- Basis is enumerated and nutrition values cannot be negative.
- `nutrition_fact_id` includes food identity in its deterministic hash to avoid cross-food collision.

### food_encounters

- `encounter_id` is primary; `(owner_user_id, idempotency_key)` is unique.
- Core event identity, date, meal type, fragment, parsed identity, and schema are required.
- `resolved_food_id` uses `ON DELETE SET NULL` so append-only history survives food removal.
- `selected_source_id` intentionally has no foreign key: historical provenance must survive source replacement/deletion.
- The RPC acquires an idempotency advisory lock before checking/incrementing/inserting.

## RLS And Service Role

RLS protects owner-scoped reads for future authenticated users and allows read-only shared/official foods. Authenticated writes are only through `upsert_food_knowledge_v1` and `save_food_encounter_v1`, which validate `auth.uid()` against the requested owner. The current Streamlit server uses a secret or legacy service-role key, which assumes the database `service_role` and bypasses RLS; therefore repository queries always add an owner filter and RPC calls carry an explicit owner.

This is acceptable only for the current server-side single-user MVP. The service key must never be sent to client HTML. Supabase Auth and per-user JWTs remain out of scope.

## Delete And Rollback Review

- Normal product behavior archives food rather than deleting it.
- Deleting a food cascades aliases and nutrition rows.
- Encounter history remains with `resolved_food_id = null`.
- Owner cleanup deletes Encounters first, then foods.
- Full rollback drops RPCs before dependent tables and drops the trigger function after tables, avoiding dependency-order failure.

## Remaining Verification

- Apply migration to a clean staging Supabase project.
- Run `supabase/verification/pr12_acceptance.sql` and save results.
- Exercise RLS with anon, authenticated owner A, authenticated owner B, and service role.
- Confirm PostgREST schema cache exposes the three RPCs.
- Run concurrent duplicate requests against real PostgreSQL.
- Confirm rollback and logical restore in staging.

Until these are complete, Migration status is reviewed but not production-accepted.
