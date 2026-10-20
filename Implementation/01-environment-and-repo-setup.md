# Part 01 — Environment & Repository Setup

**Depends on:** nothing (this is the starting point)
**Feeds into:** every other part
**Owner persona:** whoever sets up the project skeleton first (commonly the backend lead)

> **Revision 2 (2026-10-20, examiner feedback):** adds a `server/` workspace (Node.js + Express + TypeScript) and a local MongoDB to the skeleton, for M1, M2 and M5. Everything below stays valid. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

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

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** ✅ **Step 1 built** (2026-10-20, uncommitted): `server/` workspace, local MongoDB, env template, pre-commit hooks, runbook. Still open: the human second-person runbook dry run.

**Why:** the application layer becomes MERN (master plan §5). Node.js and MongoDB need a fixed place in the monorepo before Parts 07–09 and 15 are reworked. The existing layout, tooling and config strategy do not change. They gain one workspace and one database.

### R2.1 Layout additions
- `server/`: the Node.js + Express application API (Parts 07 §B, 09, 13–15 server side), with its own `package.json`, lock file, `tsconfig`, tests and `.env.example`. It is independently runnable, like every other top-level directory.
- `backend/` keeps its name and becomes the internal **ML inference service** (Part 07 §A). It is not renamed, so history, imports, docs and the `heatwave_api` package stay stable.
- `config/` stays the single home of shared non-secret config. `server/` reads the same `regions.yaml`, `risk_classes.yaml`, `alert_channels.yaml`, `notification_templates.yaml`, `notification_recipients.yaml` and `feature_labels.json` through env-var paths, never copies.
- `config/geo/`: the Maharashtra boundary file used by the map (Part 10 R2), with its source and licence recorded in a README.

### R2.2 Tooling
- **Node.js 22 LTS** for both `frontend/` and `server/` (already pinned in `.nvmrc`), npm with a committed `package-lock.json` per workspace.
- **TypeScript** in `server/`, matching the frontend. The same ESLint (typescript-eslint) and Prettier settings, and the existing pre-commit hooks extended to `server/`.
- **MongoDB 7** locally, either the official container image or a local MongoDB Community install (the runbook documents both). There is no cloud dependency for local development.
- **Test tooling for `server/`:** Vitest (as in the frontend), HTTP-level tests, and an in-memory MongoDB for tests, so no developer needs a running database to run the suite (Part 17 R2).
- **Dependency budget** (clarification, 2026-10-20: no unnecessary frameworks or services). Anything beyond this list needs a one-line reason in the Part 01 log:

  | Purpose | `server/` runtime | Why this and not more |
  |---|---|---|
  | HTTP | Express 5 | the "E" in MERN |
  | MongoDB | Mongoose | the MERN-standard ODM; collection validators are also kept in the database (Part 08 R2) |
  | Validation | zod | request/response schemas that also generate `openapi.json` |
  | Auth | jsonwebtoken, bcryptjs | the token and the password hash (Part 15 R2); pure JS, no native build |
  | Config | js-yaml | reads the shared `config/*.yaml` |
  | CORS | cors | small, standard |

  Dev only: TypeScript, tsx, Vitest, supertest, mongodb-memory-server, ESLint, Prettier.
- **Not added:** no message queue, no Redis, no separate notification service, and no logging, rate-limit or scheduler framework. The rate limit (a sliding window, as in the Python service), JSON request logging and the in-process notification queue are a few dozen lines each. Scheduling uses the OS scheduler already documented in Part 02. The frontend adds **no** runtime dependency for Revision 2: the map is SVG (Part 10 R2.2), and charts in Part 14 use the same approach unless a charting library is justified then.

### R2.3 Configuration and secrets
New variables, all in `server/.env.example` with placeholders and in `docs/configuration-and-secrets.md`:
- `MONGODB_URI` (local default points at `localhost`; staging/production values are secrets, Part 18 R2).
- `JWT_SECRET`, `JWT_TTL_MINUTES` (Part 15 R2). The server refuses to start with the placeholder secret outside local/test, the rule `AUTH_SECRET_KEY` already follows.
- `ML_SERVICE_URL`, `ML_SERVICE_TOKEN` (the internal call to FastAPI, Part 07 §A).
- `CORS_ALLOWED_ORIGINS`, `PORT` (the Node API defaults to `4000`; the ML service stays on `8000`), `NOTIFICATIONS_MODE` and the provider variables, moved conceptually from `backend/.env.example` (Part 09 R2).
- `frontend/.env.example`: `VITE_API_BASE_URL` points at the Node API (`http://localhost:4000`) once the Part 07 §B transition switches it. No other new frontend variable (the map is plain SVG, Part 10 R2.2).

### R2.4 Runbook additions (`docs/local-dev-runbook.md`)
1. Start MongoDB (container or local service).
2. `cd server && npm ci`, then copy `.env.example` to `.env`.
3. Start the ML service (step 6, unchanged), then the Node API, then the frontend (step 7).
4. Seed: create the first official user and score every place (Part 15 R2, Part 11 R2 CLI).
5. Verify: sign in → Maharashtra map shows coloured places (Part 11 R2).

### R2 acceptance criteria
- [x] `server/` workspace exists with lock file, lint, format and test scripts passing on a skeleton. *(2026-10-20: Express 5 + TypeScript skeleton with `/health`, readiness against MongoDB, the `/api/v1` envelope, request id, JSON access log, 404/500 handling; `npm run typecheck · lint · format:check · test · build` all pass, 37 tests. Log: `docs/logs/01-environment-and-repo-setup.md`, Update 2026-10-20.)*
- [x] Local MongoDB documented (container and native install), with a connectivity check in the runbook. *(Runbook step 6a; `npm run db:check`, read-only. Checked against a native MongoDB 7.0.31; the container path is documented but was not exercised.)*
- [x] `server/.env.example` and `docs/configuration-and-secrets.md` list every new variable. The secret placeholders are refused outside local/test. *(`JWT_SECRET` and `ML_SERVICE_TOKEN`: the placeholder or under 32 characters stops startup in staging/production; tested.)*
- [x] Pre-commit hooks cover `server/`. *(`server-prettier`, `server-eslint` in `.pre-commit-config.yaml`; pass on the new files. The `detect-secrets` hook calls `uv`, which is not installed on the development Mac, so it was run directly from `.venv`: clean.)*
- [ ] Runbook updated with steps R2.4 and re-validated by a second person, together with the outstanding Part 01 dry run. *(**Partly.** Runbook updated with steps 6a (MongoDB) and 6b (Node API), checked by an automated run on macOS. Seeding (users, scoring) arrives with later steps. The second-person dry run is still outstanding.)*
