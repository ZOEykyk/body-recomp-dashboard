# Development Standard

## Branch Naming

Use descriptive branches:

- `codex/pr0-bodyos-foundation-v1`
- `codex/pr6-2-calorie-intelligence-v1`
- `fix/body-score-recalculation`

Prefer `codex/{prd-or-feature-name}` for Codex-assisted work.

## PR Naming

Use a clear title that identifies the scope:

- `[codex] PR0 BodyOS Foundation v1.0`
- `[codex] PR6.2 Calorie Intelligence v1`
- `[fix] Body Score recalculation compatibility`

## Issue Severity

- `P0 Critical`: Data loss, app cannot start, broken save/import, or severely misleading dashboard output.
- `P1 High`: Major user-facing behavior is wrong, core metrics are unreliable, or important workflows are blocked.
- `P2 Improvement`: Useful quality, reliability, documentation, or UX improvement.
- `P3 Idea`: Future concept, exploratory direction, or non-urgent enhancement.

## Definition of Done

A change is done only when:

- PRD or requirement exists.
- Implementation is completed.
- `python -m py_compile app.py` passes, or the environment-specific equivalent is documented.
- Validation scenario is documented.
- README or docs are updated if behavior changes.
- Backward compatibility is considered.
- PM review is completed before merge.

## Review Checklist

- Scope matches the PRD or request.
- No unrelated refactors are included.
- Existing CSV records remain readable.
- Ordinary app launch does not silently rewrite historical records.
- Japanese and English import keys still work where applicable.
- Manual user values continue to override automatic estimates.
- User-facing labels and documentation are consistent.
- Failure modes are understandable and recoverable.

## Validation Checklist

- Run `python -m py_compile app.py`.
- Test the changed workflow with at least one realistic record.
- Confirm existing CSV compatibility with `normalize_columns()`.
- Confirm README or docs links render correctly.
- Confirm no app behavior changed for documentation-only PRs.

## README Update Rule

Update README when a change affects setup, data input, user-visible behavior, scoring, storage, or project documentation.

For detailed product rules, prefer docs under `docs/` and link them from README instead of expanding README indefinitely.

## Backward Compatibility Rule

BodyOS must preserve existing `records.csv` compatibility unless a PR explicitly declares and migrates a breaking schema change.

Historical records are immutable by default:

- New business rules apply to new imports, newly created records, explicit edits, or explicit re-imports.
- App launch, dashboard rendering, and in-memory display helpers must not save migrated historical values.
- Any historical migration must be a separate, user-confirmed workflow with clear before/after behavior.

When adding columns:

- Add them as optional columns when possible.
- Provide defaults in normalization.
- Preserve existing Japanese and English aliases.
- Avoid changing the meaning of existing columns without a migration plan.
