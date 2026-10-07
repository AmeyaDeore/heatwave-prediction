# Log: merge of Parts 07–09 into `main`

| | |
|---|---|
| Date | 2026-10-07 |
| Change | `part-07/backend-api` merged directly into `main` (no PR, at the owner's request) |
| Tests | Full repository suite run on the merged tree (see Verification) |

## Summary

`main` and `part-07/backend-api` had diverged. The branch had been rebuilt, so `main` held copies of Parts 03–06 with different hashes, plus an **earlier, different Part 07 backend** (`c62a769`, merged through PR #1). The branch held the Part 07 backend that Parts 08 (SQLite) and 09 (notifications) are built on. The two backends shared no structure, so they could not be combined file by file.

## What the merge kept

- **Backend (`backend/`), backend config and backend docs:** the branch version (Parts 07, 08 and 09).
- **Removed from `main`:** the earlier Part 07 modules and tests that only it used (`api.py`, `deps.py`, `security.py`, `notifications.py`, `inference.py`, `predictions.py`, `reference.py`, `responses.py`, `observability.py`, `actions.py`, `analytics.py`, `cli.py`, `db/migrations/0001_initial.sql`, `tests/api_support.py`, `test_auth.py`, `test_conventions.py`, `test_actions_cli.py`, `test_weather_analytics.py`). Their old `0001_initial.sql` would have clashed with the branch's migration runner.
- **ML, from `main`:** fix `d3f2a5c`. The explainer is keyed by the registered model version, and the Part 06 plan and log record the re-verification.
- **From `main`:** the project-skills commit (`29cf688`) and the ruff `flake8-bugbear` setting.
- **`docs/api/openapi.json`:** regenerated from the merged app (15 paths, including `/advisories` and `/alerts/{id}/attempts`).
- **`uv.lock`:** re-locked against the branch's `backend/pyproject.toml`.

## Verification

- `uv run pytest -q` (whole repository) on the merged tree passed. The count is in the commit message.
- `uv run pre-commit run --all-files` passed.

## Open items

- Anyone who based work on `main`'s earlier Part 07 (for example frontend code using `meta.warnings` or `/reference`) needs to move to the contract in `docs/api/README.md`.
