# PR15.1 Performance Report

## Scope

PR15.1 optimizes existing BodyOS runtime paths. It does not change nutrition,
Workout Intelligence, Canonical Schema 1.0, CSV/JSON schemas, or stored records.

Method: measure, identify bottlenecks, optimize, then repeat the same local
benchmark. Timings use `time.perf_counter()` and report median values after
three warmups. Results are development measurements, not an SLA.

## Environment

- Host: macOS (`darwin`)
- Python: 3.9.6
- App: local Streamlit at `http://localhost:8515`
- Stored history: 49 CSV records (133 physical data lines because fields contain newlines)
- Performance fixture: 100 Personal Food records and 11 capture items
- Benchmark: 25 iterations unless noted otherwise
- Base revision: `4a8fdfe` (`main`)

Hosted Streamlit Cloud cold start and live Supabase round-trip latency were not
measured because this environment has no production secrets. No values are
estimated for those paths.

## Before And After

| Operation | Before median | After median | Change |
|---|---:|---:|---:|
| Rerun Food Knowledge path | 33.531 ms (7 rebuilds) | 4.648 ms (1 shared build) | -28.883 ms / 86.1% faster |
| Warm local Food search | 3.228 ms | 0.713 ms | -2.515 ms / 77.9% faster |
| Food Resolver | 4.061 ms | 0.712 ms | -3.349 ms / 82.5% faster |
| Nutrition Intelligence, 11 items | 77.298 ms | 62.186 ms | -15.112 ms / 19.6% faster |
| Full-history Nutrition comparison | 154.8 ms intermediate | 53.798 ms | -101.002 ms / 65.2% faster |
| Canonical Builder + validation | 1.228 ms | 1.239 ms | +0.011 ms / within run noise |
| Daily Nutrition aggregate | 0.190 ms | 0.183 ms | -0.007 ms / 3.7% faster |
| Repository JSON snapshot | 2.171 ms | 2.167 ms | -0.004 ms / unchanged |
| CSV parse | 1.273 ms | 1.253 ms | -0.020 ms / unchanged |
| Workout Intelligence | 0.030 ms | 0.033 ms | +0.003 ms / within run noise |
| Cached static Catalog retrieval | not separately cached | <0.001 ms | below timer display precision |
| Local JSON Food edit | not isolated | 2.750 ms | target check only |

The full-history Before value was captured after the first Resolver copy
optimization but before limiting comparisons to the seven days that can affect
the result. It is labeled intermediate so it is not confused with a clean-main
measurement.

## Actual Streamlit

The real app was opened and exercised in the in-app browser after optimization.

| Interaction | Observed |
|---|---:|
| Search query commit and complete rerun | 271 ms |
| Add Food and complete rerun | 274 ms |
| Mobile viewport | 390 x 844 px |
| Mobile horizontal overflow | none (`scrollWidth = innerWidth = 390`) |
| Browser console errors | 0 |

Browser interaction timings include rendering and browser automation overhead.
Dashboard, Nutrition Intelligence, Smart Food Capture, Canonical Preview, JSON
Import, and the captured daily nutrition result all rendered without a
Streamlit exception.

## Root Bottlenecks

1. `FoodMasterRepository` and the Supabase client were reconstructed at module rerun.
2. `current_food_knowledge()` was called seven or more times during a normal widget rerun.
3. Static and personal knowledge had the same lifetime and were rebuilt together.
4. Resolver and search copied whole catalogs for each query.
5. Nutrition comparisons evaluated every historical day although only the preceding seven can affect the output.
6. CSV normalization and Dashboard projections repeated with unchanged input.
7. Food Knowledge analytics queried optional repository data even when the user did not open the management area.

## Cache Strategy

- Repository/client: `st.cache_resource`, process lifetime, no arguments and no secrets in its cache key.
- Static Food Knowledge: `st.cache_data`, 3600-second TTL.
- Personal Food Knowledge: `st.cache_data`, 30-second TTL, keyed by `user_id` and repository write revision.
- GitHub records read: `st.cache_data`, 30-second TTL, keyed only by public repository identity.
- Local records read: keyed by resolved path, modification time, and size.
- CSV normalization: content-keyed `st.cache_data`.
- Dashboard projection: content-keyed `st.cache_data` plus current date.
- Nutrition and Workout Intelligence render results: content-keyed cache with 30-second TTL.

Canonical Builder remains uncached. Its median is 1.239 ms, and validation must
always govern save eligibility. Adding another mutable-state cache there would
increase correctness risk without a measurable user benefit.

## Invalidation And Isolation

- Every successful repository write increments a thread-safe process-local revision.
- The next Personal Food read uses a new `(user_id, revision)` key immediately.
- The 30-second TTL bounds cross-process/external-write staleness.
- CSV save clears GitHub read, local read, and normalized-record caches.
- Dashboard cache keys include the DataFrame content; changed records render immediately.
- Personal cache entries always include `user_id`; validation confirms a second owner cannot read the first owner's foods.
- Cache keys, timing samples, and logs contain no Supabase keys or record contents.
- RLS, owner filters, schema, and Supabase migrations are unchanged.

## Rerun Audit

- One Food Knowledge snapshot is now shared by Dashboard, Smart Food Capture,
  legacy meal estimation, save resolution, and Encounter persistence in a rerun.
- Search runs against the in-memory snapshot; no query-per-keystroke DB call remains.
- Static catalogs are copied only on the initial cached build.
- Resolver/search retain pure input behavior while copying selected result objects.
- Optional Food Knowledge metrics and management queries run only after the
  `Food Knowledge詳細を表示` toggle is enabled.
- Smart Food Capture session state remains limited to current capture items and
  widget values. No additional cached mutable session object was introduced.

## Correctness Validation

- Canonical fixture SHA-256 is unchanged:
  `7efc99d403fe5b1424f4ed10c2e9eb9f59d9d8844938cc021405b72971c82afb`.
- New Food write revision invalidates Personal Food cache immediately.
- Changed Dashboard input bypasses the previous projection cache.
- PR15 user-label, basis inference, 3 purchased / 2 consumed, P/F/C restore,
  Unknown handling, Personal Master re-search, and Encounter idempotency pass.
- `records.csv`, Workout history, Canonical Schema 1.0, CSV schema, and JSON schema are unchanged.

## Remaining Limits

- Community Cloud sleep, redeploy, Python import, and live Supabase latency still
  dominate cold starts and require hosted acceptance measurements.
- The Nutrition engine is the largest remaining local pure-compute path at about
  54-62 ms. It is within the warm interaction budget and is cached at the Dashboard boundary.
- External writes from another worker may remain stale for at most the 30-second Personal Food TTL.
- OCR/Vision latency is not part of PR15.1. The instrumentation and cached Food
  Knowledge boundary are ready to separate OCR cost from Resolver and persistence cost in PR16.

## Acceptance Regression: Immediate Confirmed Search

Acceptance testing found that the Personal Food cache depended only on the
currently active backend's process-local revision. In `fallback_json` mode, a
transition such as primary revision `1` to fallback revision `1` could reuse the
same `(user_id, revision)` cache key even though the underlying data changed.
Smart Food Capture also had no explicit cache invalidation callback after
`confirm_capture_food()`.

The fallback adapter now owns one monotonic revision across primary/fallback
transitions, and the Smart Food Capture confirmation path explicitly clears the
Personal Food cache before `st.rerun()`. Revision remains the normal cache key;
explicit clearing is a guard against stale process-local entries.

Validated without waiting for the 30-second TTL:

| Repository path | Revision | Result |
|---|---:|---|
| Local JSON | `0 -> 1` | immediate `personal_master` hit |
| Supabase adapter | `0 -> 1` | immediate `personal_master` hit |
| Primary to fallback switch | `1 -> 2` | immediate `personal_master` hit |

The saved snapshot contains one active `PR15.1テスト バナナ②` record and one
verified `explicit_user_label` nutrition source. Re-search restores `99 kcal`,
`P 3.0 g`, `F 0.5 g`, `C 13.0 g`, `per_item`, `過去の確認値`, and `High`.
The actual Streamlit component was also exercised: the save rerun completed in
263 ms, displayed revision `1`, and immediately replaced the Unknown candidate
with the Personal Food Master candidate. Browser console errors were zero.

## Streamlit Cloud Food Knowledge Diagnostics

The local adapter regression passes but the hosted failure remains reproducible,
so Smart Food Capture now includes an opt-in `Food Knowledge診断を表示` panel.
It reports metadata from the production save, readback, cache, and search paths;
it never reports credentials, raw user IDs, food names, or nutrition values.

Use the panel immediately after a confirmed-label save and again with the same
search text:

- `repository_status.connection = Fallback` identifies a Supabase-to-local switch.
- Different save/search `user_key` values identify owner configuration drift.
- `post_save_snapshot_contains_food = false` means the returned save object was
  not visible from the repository snapshot used for the next read.
- A lower `cached_personal_food_count` or missing `food_id` in the current
  knowledge trace identifies a stale or different read snapshot.
- `drop_reason = inactive` identifies a non-active stored record.
- `drop_reason = source_not_selected` plus `source_selection_status` identifies
  invalid, expired, conflicting, or absent nutrition source metadata.
- `drop_reason = included` confirms that Personal Food candidate construction
  succeeded and shifts investigation to Streamlit widget/display state.

The panel is diagnostic instrumentation, not a second lookup implementation:
candidate results and drop reasons are emitted by the same search loop used by
the UI. The definitive hosted root cause remains unconfirmed until these values
are captured from the failing Streamlit Cloud process.
