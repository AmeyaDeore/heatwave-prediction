# Part 01 — Environment & Repository Setup

**Depends on:** nothing (this is the starting point)
**Feeds into:** every other part
**Owner persona:** whoever sets up the project skeleton first (commonly the backend lead)

## 1. Objective

Establish the repository structure, tooling, configuration strategy, and local development environment so that every subsequent part (data pipeline, backend, frontend) has a fixed, agreed-upon place to live and a consistent way to run locally.

## 2. Repository strategy

Decide and document: **monorepo** (recommended for a 3-person mini-project) containing three top-level concerns, versus separate repos per concern.

Recommended monorepo layout (directories, not files, described conceptually):

- `data/` — raw and processed datasets, data collection scripts, notebooks used for exploration. Large raw files are not committed; only sample/small reference data and generation scripts are.
- `ml/` — everything from Part 03–06: preprocessing code, training scripts, evaluation reports, the SHAP integration, and the exported trained model artifact(s).
- `backend/` — the FastAPI service (Parts 07–09, 15), its own dependency manifest, its own config.
- `frontend/` — the web dashboard (Parts 10–14), its own dependency manifest and build config.
- `docs/` — architecture diagrams, API contracts, this implementation plan set itself, and any decision records.
- `infra/` or `deploy/` — deployment manifests, CI/CD pipeline definitions (Part 18).
- `tests/` — cross-cutting/integration tests that span backend + frontend + ML (unit tests for each concern live alongside that concern instead).

Each top-level directory should be independently runnable: a developer working only on the frontend should not need the ML stack installed, and vice versa.

## 3. Tooling decisions to lock in

- **Python version** for `ml/` and `backend/` — pin one version and record it; all three should use the same interpreter version to avoid pickle/model-artifact incompatibility between training and serving.
- **Package/dependency management** — pick one approach per language ecosystem (e.g., a Python virtual-environment manager with a lock file for `ml/`+`backend/`; a JS package manager with a lock file for `frontend/`) and commit the lock files so builds are reproducible.
- **Code formatting/linting** — agree on one formatter and one linter per language before any code is written, so reviews don't get bogged down in style.
- **Pre-commit checks** — at minimum: formatting check, lint check, and "no secrets committed" check.
- **Editor/agent config** — a shared `.editorconfig` and any AI-agent-specific instruction files (if using Claude Code or similar) should live at the repo root so every contributor/agent session behaves consistently.

## 4. Configuration & secrets strategy

This must be decided now because every later part (API keys for NASA POWER, SMS/email provider credentials, database URL, model artifact path) depends on it.

- **Environment variables, not hard-coded values**, for anything that differs between local/staging/production: database connection string, weather-data-source API keys, notification provider credentials, model artifact path/version, allowed CORS origins, log level.
- **A single source of truth per environment** — one example/template file documenting every required variable name and a placeholder value, committed to the repo; the real values are never committed.
- **Separation by concern** — backend config, ML pipeline config, and frontend build-time config should be distinct sets of variables even if they overlap conceptually (e.g., "which risk thresholds to use" might be read by both the ML pipeline and the backend, so it should be defined once and referenced, not duplicated).
- **Secrets rotation plan** — even for a mini-project, document how a leaked/expired API key would be rotated (who owns the NASA POWER key, who owns the SMS/email provider key).

## 5. Local development environment

Define, as a written runbook (not code), how a new contributor goes from a clean checkout to a running system:

1. Install the pinned language runtimes.
2. Create and activate the Python environment for `ml/` and `backend/`; install locked dependencies.
3. Install frontend dependencies.
4. Copy the environment-variable template to a local, git-ignored config file and fill in local values (a locally running SQLite file is fine; a dummy/test API key for weather data if the real one is rate-limited).
5. Run the data pipeline once (Part 02/03) to produce a local dataset, OR use a committed small sample dataset for pure frontend/backend development so ML work isn't a blocker for the other two tracks.
6. Start the backend service locally.
7. Start the frontend dev server locally, pointed at the local backend.
8. Verify: opening the dashboard shows data end-to-end.

This runbook should be re-validated (dry-run by a second person) once Parts 07 and 10 exist, since it can't be fully verified until backend and frontend actually exist.

## 6. Version control workflow

- Branch naming convention aligned to the part numbers in this plan set (e.g., a branch per part) so work can be reviewed and merged incrementally rather than as one giant PR.
- Protected main branch requiring at least one review.
- Commit message convention (even a lightweight one) so the eventual `18-deployment` changelog/versioning has something to work from.

## 7. Non-functional requirements for this part

- A new contributor should be able to go from `git clone` to "frontend loads, showing at least placeholder/sample data" in under 30 minutes following the runbook.
- No secret value should ever be committed; the pre-commit secret check should catch this before it reaches version control.
- The repo structure must not need to change shape once Parts 02–18 begin — restructuring mid-project is expensive across three parallel workstreams.

## 8. Acceptance criteria / "done"

- [x] Repo created with the directory layout above (even if most directories are still empty placeholders with a short README each).
- [x] Language/runtime versions pinned and documented.
- [x] Lock files present for both ecosystems.
- [x] Formatter + linter configured and passing on the empty/skeleton repo.
- [x] Environment-variable template file exists and lists every variable name later parts will need (this list will grow — treat it as a living document referenced by Parts 02, 07, 09, 18).
- [ ] Local dev runbook written and validated by at least one person other than its author. *(Written ✅; automated clean-checkout dry run passed 2026-09-28 ✅; **human second-contributor dry run still outstanding** — record it in `docs/local-dev-runbook.md` → Validation log.)*
- [x] Branching/PR convention documented.

**Verification (2026-09-28):** `ruff check`, `ruff format --check`, `eslint`, `prettier --check`, `pytest` and `pre-commit run --all-files` all pass. `detect-secrets` blocks a planted credential.

## 9. Handoff note template (fill in once this part is complete)

> Repo is live at: <location>. Layout matches Section 2. Config template lives at: <path>. Anyone starting Part 02 or Part 07 can now assume a working, empty skeleton with agreed tooling.

**Filled in:** Repo is live at: this monorepo (local; no remote pushed yet). Layout matches Section 2, plus a root `config/` for shared non-secret values (ADR 0001). Config templates live at: `backend/.env.example`, `ml/.env.example`, `frontend/.env.example`, with the inventory in `docs/configuration-and-secrets.md`. Anyone starting Part 02 or Part 07 can now assume a working, empty skeleton with agreed tooling.
