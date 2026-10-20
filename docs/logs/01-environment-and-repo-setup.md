# Log 01 — Environment and repository setup

| | |
|---|---|
| Plan | [Implementation/01-environment-and-repo-setup.md](../../Implementation/01-environment-and-repo-setup.md) |
| Status | Complete, except one item: a **human second-contributor dry run** of the runbook is still outstanding |
| Date | 2026-09-28 |
| Branch / commits | `main` · `f9b562f` feat(setup): initialize repo layout, workspace tooling, and environment |
| Tests | 2 (backend health check, ML package import) |

## Summary

Set up the monorepo skeleton that every later part builds on: one repository holding data, ML, backend, frontend, docs and deployment, with pinned runtimes, a single Python lock file shared by the ML pipeline and the backend, linters/formatters, secret scanning, environment templates and a local-dev runbook.

## What was built

**Layout** (ADR 0001):

```
data/        raw/ processed/ local/ (git-ignored contents) · sample/ (committed)
ml/          heatwave-ml package (src/heatwave_ml), tests, artifacts/ (git-ignored)
backend/     heatwave-api package: FastAPI app (main.py, /health), Settings (config.py), tests
frontend/    Node 22 project: ESLint (flat config) + Prettier; framework deferred to Part 10
config/      shared, non-secret config: regions.yaml, risk_classes.yaml
docs/        runbook, configuration & secrets, decisions/ (ADRs)
deploy/ tests/   placeholders with READMEs
Implementation/  the 18-part plan set (kept at root; referenced by path)
```

**Tooling and pins**

| Area | What |
|---|---|
| Python | 3.13 (`.python-version`, `requires-python`) for both `ml/` and `backend/` |
| Dependencies | uv workspace (`pyproject.toml` at root, members `ml`, `backend`), **one `uv.lock`**, so the backend unpickles models with the exact library versions used in training |
| Node | 22 LTS (`.nvmrc`, `engines`), npm with `package-lock.json` |
| Python lint/format | Ruff (`line-length 100`, rules E/W/F/I/B/UP/SIM) |
| JS lint/format | ESLint flat config + Prettier |
| Git hooks | `.pre-commit-config.yaml`: merge-conflict, YAML/TOML, EOF, whitespace, large files, private keys, **detect-secrets** (with `.secrets.baseline`), ruff check/format, prettier, eslint |
| Line endings | `.gitattributes` (`* text=auto eol=lf`) + `.editorconfig` |

**Configuration**

- Three env templates: `backend/.env.example`, `ml/.env.example`, `frontend/.env.example` (frontend vars are public, `VITE_` prefix).
- Shared values live once in `config/`: `risk_classes.yaml` (the `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE` vocabulary and IMD thresholds) and `regions.yaml` (5 Mumbai regions: Mumbai, Kurla, Andheri, Dharavi, Colaba; all in the `coastal` zone).
- Backend `Settings` (pydantic-settings) resolves relative paths against the repo root.

**Docs:** `docs/local-dev-runbook.md` (clone → running system), `docs/configuration-and-secrets.md` (rules, variable inventory, secret ownership and rotation), `CONTRIBUTING.md` (branch naming `part-NN/<slug>`, Conventional Commits, PR rules), `.github/pull_request_template.md`, ADR `docs/decisions/0001-repo-and-tooling.md`.

## Key decisions and why

- **Monorepo:** a 3-person team with shared contracts (risk classes, API shape) can change both sides in one PR.
- **One Python version and one lock for ML + backend:** a pickled model only loads safely with the versions that wrote it.
- **detect-secrets through uv:** pure Python, works on Windows, versions pinned by the lock.
- **Frontend framework deferred to Part 10:** Part 10 owns that choice; env names assume Vite provisionally.

## Verification

2026-09-28: `ruff check`, `ruff format --check`, `eslint`, `prettier --check`, `pytest` and `pre-commit run --all-files` all passed. `detect-secrets` blocked a deliberately planted credential. An automated clean-checkout dry run of the runbook passed.

## Deviations from the plan and issues found

- Added a root `config/` directory (not in the plan's layout) to hold values shared by ML and backend.
- `Implementation/` stayed at the repo root rather than moving under `docs/`, because existing workflows reference that path.

## Open items / follow-ups

- **Human dry run of the runbook by a second contributor** (record it in the runbook's validation log). Steps 7–8 can only be checked once Parts 07 and 10 exist.
- The backend has no ML dependencies yet. Part 07 must add the inference subset (scikit-learn, xgboost, shap); the shared lock keeps versions identical.
- No remote repository has been pushed yet.

## Handoff

Anyone starting Part 02 or Part 07 can assume a working skeleton with agreed tooling, env templates and the shared `config/` files.

## Update 2026-10-20: Revision 2 step 1 (Part 01 R2), `server/` workspace and local MongoDB

| | |
|---|---|
| Plan | [Part 01 Revision 2](../../Implementation/01-environment-and-repo-setup.md#revision-2--examiner-feedback-2026-10-20), master plan §4.1 step 1 |
| Status | Step 1 complete. Open: the pre-commit hooks were run directly, not through `uv` (not installed here); the container MongoDB path is documented but not exercised; the human runbook dry run is still outstanding |
| Branch | `part-10/frontend-architecture` (uncommitted) |
| Tests | 37 new (server). Existing suites unchanged from the baseline |

### Baseline before any change (recorded, nothing cleaned up)
- Working tree: 48 status entries (the uncommitted Part 10 frontend, the Revision 2 plan docs, untracked tooling files). Recorded and compared afterwards.
- Python (`.venv`, `DYLD_FALLBACK_LIBRARY_PATH` libomp workaround): **281 passed, 3 skipped, 6 errors**. The 6 errors are all `backend/tests/test_production_model.py`. Cause: its skip guard checks only that `ml/artifacts/runs/` exists, and the local Apple Silicon training run made earlier this session (git-ignored, `20261020T104511Z-d89b8a`) now exists there but is not the committed production bundle. They are pre-existing for this step and were not touched. Runbook Troubleshooting has the fix options. Earlier the same day, before that run existed, it was 281 passed, 9 skipped.
- Frontend: 145 passed; typecheck, lint, format clean.

### What was built
| Path | Role |
|---|---|
| `server/package.json`, `package-lock.json` | Node 22 workspace. Runtime deps **express 5, mongoose 9, zod 4** only (the Part 01 R2.2 budget; `jsonwebtoken`, `bcryptjs`, `js-yaml`, `cors` are deferred to the steps that use them). Dev deps at the frontend's majors (TypeScript 5.9, Vitest 4) plus tsx, supertest, mongodb-memory-server, ESLint 9, Prettier 3 |
| `server/tsconfig*.json`, `eslint.config.js`, `.prettierrc.json`, `.prettierignore`, `vitest.config.ts` | Tooling mirroring `frontend/` (NodeNext ESM; `no-console` outside the CLI) |
| `server/src/config.ts` | Env validation with zod. Errors name the variable and rule, never the value. `JWT_SECRET` and `ML_SERVICE_TOKEN` are refused outside local/test if they are the placeholder or under 32 characters. `MONGODB_URI` must name its database |
| `server/src/app.ts` | `createApp` with `GET /health` (same body as FastAPI), `GET /api/v1/health/ready` (envelope; 503 when MongoDB is down), NOT_FOUND envelope, error handler (500 INTERNAL_ERROR quoting the request id; no internals leaked) |
| `server/src/http/` | Envelope + `ApiError` (same taxonomy as FastAPI); request id (caller's if a safe token, else 16 hex) and the access log |
| `server/src/logger.ts` | JSON-lines logger, the FastAPI log shape |
| `server/src/db.ts` | Mongoose connection: ping, read-only server info, close. MongoDB down at startup does not stop the API; readiness retries |
| `server/src/main.ts` | Entry point with graceful SIGINT/SIGTERM shutdown |
| `server/src/cli/db-check.ts` | `npm run db:check`, read-only connectivity check (exit 0/1/2) |
| `server/src/test/mongo.ts`, `*.test.ts` | In-memory MongoDB 7.0.14 for tests; config (22), app (10), db (5) tests |
| `server/.env.example`, `server/README.md` | Template and workspace docs |
| `.pre-commit-config.yaml` | `server-prettier`, `server-eslint` hooks (header comment updated) |
| `.gitignore` | `server/dist/`, `coverage/` |
| `docs/local-dev-runbook.md` | MongoDB in the runtimes table, `server` install and env copy, **step 6a** (container or native MongoDB + `db:check`), **step 6b** (Node API), quality checks, three troubleshooting entries, validation-log row |
| `docs/configuration-and-secrets.md` | `server/.env.example` in the template table, six inventory rows, ownership rows for the new secrets |
| `Implementation/01-…md` | R2 checklist: three items ticked with evidence |

### Key decisions
- **Same conventions as FastAPI** (envelope, error codes, `/health` body, request-id format, JSON log shape), so the Part 10 frontend and the logs treat both services alike.
- **Own database name, required in the URI** (`heatwave_local`). The developer's MongoDB here already holds other projects' databases. Requiring the name avoids writing into a default `test` database.
- **MongoDB down ≠ API down:** liveness stays 200, readiness 503, and it reconnects on the next check. FastAPI fails fast only for the model, which it cannot work without.
- **Validate later-step secrets now**, so a staging deploy can never start with the placeholder.
- **Tests never use the developer's MongoDB:** an in-memory 7.0.14 server per run.
- **`pragma: allowlist secret`** on the placeholder and the fake test credentials, the same convention the backend uses for its placeholder.

### Verification (actual results)
```
cd server
npm run typecheck                 -> clean
npm run lint                      -> clean
npm run format:check              -> All matched files use Prettier code style!
npm test                          -> 3 files, 37 passed (first run ~34 s incl. MongoDB 7.0.14 download; then ~2 s)
npm run build                     -> dist/ emitted
npm run db:check                  -> reachable, server 7.0.31, heatwave_local (0 collections)
MONGODB_URI=…:27999/… db:check    -> NOT reachable, ECONNREFUSED, hint to step 6a
npm start                         -> /health 200 {"status":"ok","env":"local"}; ready 200 {ready:true, database:"ok"};
                                     /api/v1/nope 404 NOT_FOUND with echoed X-Request-ID; JSON access log; SIGTERM clean
MongoDB down (port 27999)         -> /health 200; ready 503 {ready:false, database:"unavailable"}
APP_ENV=production npm start      -> exit 2, names JWT_SECRET and ML_SERVICE_TOKEN, prints no values
pre-commit (new files)            -> all hooks pass incl. server-prettier/server-eslint; detect-secrets run directly: clean
```
Developer MongoDB database list before and after: unchanged (`heatwave_local` not created; nothing was written).
Existing suites after the change: Python 281 passed / 3 skipped / 6 errors (same as baseline), frontend 145 passed. `git status` shows no change under `backend/`, `ml/`, `config/`, `data/` or `frontend/` relative to the baseline.

### Deviations and issues
- Node 24.14 locally vs the pinned 22 (`engines` warns only). `--env-file-if-exists` needs Node ≥ 22.9, now stated in the runbook.
- `uv` is not installed here, so the `detect-secrets` hook (which calls `uv run`) was run directly from `.venv`.
- The two Step 1 config-test failures on the first run were a message-format issue (zod reported `CORS_ALLOWED_ORIGINS.0`), fixed so problems name only the variable.

### Handoff (to Revision 2 step 2)
> `server/` runs, tests and lints on its own; MongoDB is reachable through `MONGODB_URI` with `npm run db:check`. No application feature lives here yet. Step 2 (Part 02 R2 loader fix + Part 07 §A ML-service role) touches only Python and can assume this workspace exists.
