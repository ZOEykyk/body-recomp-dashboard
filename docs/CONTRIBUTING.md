# Contributing

## Contribution Principles

- One PR should solve one theme.
- Avoid scope creep.
- Prefer small, reviewable changes.
- Preserve existing records and user trust.
- Update docs when behavior changes.

## Creating PRs

1. Start from the latest `main`.
2. Create a descriptive branch.
3. Confirm the PR has a requirement, issue, or PRD.
4. Keep unrelated refactors out of the PR.
5. Run validation before requesting review.

## PR Summary

Every PR should include:

- What changed.
- Why it changed.
- User or developer impact.
- Validation performed.
- Compatibility notes when data or imports are touched.

## Validation

At minimum, run:

```bash
python -m py_compile app.py
```

If the local environment uses `python3`, document that:

```bash
python3 -m py_compile app.py
```

Also document realistic validation scenarios for changed behavior.

## Updating Docs

Update README or `docs/` when a PR changes:

- Setup.
- Data schema.
- Import format.
- Scoring.
- Calorie estimation.
- Workout normalization.
- User-visible dashboard behavior.
- Development process.

## Handling Bugs

Classify bugs by severity:

- `P0 Critical`: Data loss, app cannot start, save/import broken, or severe metric corruption.
- `P1 High`: Core workflow or major metric is unreliable.
- `P2 Improvement`: Non-blocking correctness, UX, docs, or maintainability issue.
- `P3 Idea`: Future enhancement or exploratory concept.

## Scope Control

If a PR uncovers unrelated work, document it as a follow-up instead of expanding the current PR. BodyOS should remain easy to review and safe to merge.
