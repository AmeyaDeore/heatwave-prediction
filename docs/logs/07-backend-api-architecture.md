# Log 07 — Backend API architecture (FastAPI)

| | |
|---|---|
| Plan | [Implementation/07-backend-api-architecture.md](../../Implementation/07-backend-api-architecture.md) |
| Status | Complete. Part 08 still has to review the schema (see Open items) |
| Date | 2026-10-06 |
| Branch / commits | `part-07/backend-api` (from `main` at `0fd6407`) · `15f641d` (Part 06 fix, see Log 06 Update) → the Part 07 commit that adds this log. Not yet pushed / PR not opened |
| Tests | 92 new backend tests (3 of them on the real production model), 250 total passing |

## Summary

Before starting, Part 06's checklist was re-verified on a fresh clone. It holds, and one real defect was found and fixed: explainers were keyed by the bundle's own version instead of the registered version (see Log 06 Update).

Part 07 then built the whole API service around the production model:
- **Every endpoint** in §3 (predict, weather, alerts list/get/create/patch, analytics, login/logout/me), plus the reads the dashboard needs: latest prediction per region, a prediction by id, the model's metrics, reference data, and readiness.
- **The §4 conventions:** envelope, `/api/v1`, strict validation, CORS, rate limits, idempotent alert creation.
- **Fail-fast startup** that loads the model and explainer once.
- **An error taxonomy** with partial failures made visible.
- **The draft → issued alert flow**, with per-channel delivery status.
- **SQLite persistence** through numbered migrations.

The contract is documented in `docs/api/README.md` and the generated `openapi.json`, and the decisions in ADR 0006. It was verified against fakes, against the real model, and live over HTTP with the real Open-Meteo forecast.

## What was built

| Path | Role |
|---|---|
| `backend/src/heatwave_api/main.py` | `create_app()`: lifespan (startup, or refuse to start), CORS, request-id and JSON request-log middleware, catch-all 500 envelope, `/health` liveness |
| `api.py` | 15 routes under `/api/v1`, thin handlers |
| `schemas.py` | Every request and response model, and the generic `Envelope[T]`. The `Explanation`/`Factor` models mirror Part 06's contract |
| `errors.py`, `responses.py` | `ApiError` hierarchy (client/auth/upstream/internal); handlers that turn every failure into an envelope (validation errors never echo values) |
| `services.py`, `deps.py` | The `Services` container; `assemble_services` (real startup around injectable model, forecast and notifier); per-request DB connection, `current_user`, `reader`, `rate_limit` |
| `inference.py` | `ModelService.load`: `load_production_explainer` (or a pinned `MODEL_VERSION`), Part 05 metrics from the evaluation report, normals coverage check, warm-up. `predict`: `build_features` → `explain`, under a lock |
| `weather.py` | `OpenMeteoProvider` (Part 02's adapter, 10 s timeout, 2 attempts) and `WeatherService` (forecast cached in `weather_snapshots`, keyed by the local issue date) |
| `predictions.py` | Prediction runs: forecast or client conditions, peak-day selection, persistence, one `payload()` for both POST and GET |
| `alerts.py` | Create (idempotent), update/transition, per-channel `dispatch`, `HW-YYYY-NNNN` ids |
| `analytics.py` | Trend (with IMD thresholds), risk distribution, monthly events, model performance; current weather with per-region errors |
| `actions.py` + **`config/recommended_actions.yaml`** | The deterministic recommended-actions mapping (`ACT-v1`), validated at load |
| `notifications.py` | `Notifier` protocol and `MockNotifier` (optionally fails chosen channels) |
| `security.py`, `ratelimit.py`, `observability.py`, `reference.py` | scrypt hashes and HS256 tokens; fixed-window limiter; JSON logs with request id; regions, vocabulary, channel labels, thresholds |
| `db/__init__.py`, `db/migrations/0001_initial.sql`, `db/repository.py` | Migration runner (per-migration transaction, SHA-256 of each applied file, FK check); 12-table schema; all SQL |
| `cli.py` | `heatwave-api migrate · create-user · set-password · check · openapi` (new `[project.scripts]` entry) |
| `backend/tests/` | `conftest.py` (fixtures), `api_support.py` (fakes), plus 8 test files |
| `docs/api/README.md`, `docs/api/openapi.json` | The contract (human-readable and generated) |
| `docs/decisions/0006-backend-api.md` | ADR |

**Config/env:**
- New variables (all in `backend/.env.example` and the inventory in `docs/configuration-and-secrets.md`): `RATE_LIMIT_PREDICT`, `RATE_LIMIT_ALERT_WRITES`, `RATE_LIMIT_LOGIN`, `AUTH_REQUIRED_FOR_READS`, `NOTIFICATIONS_MOCK_FAIL_CHANNELS`, `RECOMMENDED_ACTIONS_FILE`, `OPEN_METEO_FORECAST_URL`, `WEATHER_HTTP_TIMEOUT_SECONDS`, `WEATHER_MAX_ATTEMPTS`, `WEATHER_CACHE_MINUTES`.
- `MONITORED_REGIONS_FILE` and `SEASONAL_NORMALS_FILE` are now read by the backend too.

**Dependencies:**
- The backend now depends on `heatwave-ml` (a workspace source). `uv.lock` changed by that edge only, and `heatwave-api` went to 0.2.0.
- Root `pyproject.toml`: bugbear `extend-immutable-calls` for `fastapi.Depends/Query/Path`.

**Docs updated:** `backend/README.md`, `docs/README.md`, `docs/local-dev-runbook.md` §6, `config/README.md`, `frontend/README.md`, and the Part 07 checklist and handoff.

## Key decisions and why

Full table in ADR 0006. The ones a reviewer should know:

- **Live weather:** the backend calls Part 02's Open-Meteo adapter and Part 03's `build_features` itself, and caches the result in the database. There is one feature path for training and serving, the frontend sends only a region, and the service stays stateless. `conditions` lets callers supply the weather themselves (what-if, offline).
- **A prediction is a run of 1–3 days.** Each day has its own explanation, and the headline is the peak day. The Part 06 explanation is returned unchanged.
- **Recommended actions** are a versioned, config-driven, deterministic mapping, with a reason on every action. Factor rules use SHAP `share_pct` thresholds that minor factors only reach when the model really used them.
- **Persistence:** `sqlite3` with a `Repository` and numbered SQL migrations, not an ORM. The schema is portable to PostgreSQL apart from AUTOINCREMENT.
- **Auth for writes now, policy later:** alert writes always need a token, and reads are open behind a switch for Part 15. Tokens are HS256 JWTs, revocable on logout.
- **Dispatch is synchronous and per channel,** through a `Notifier` interface. The mock is instant, so the response shows the final statuses. Part 09 decides on background dispatch.
- **New model = restart.** There is no hot swap, and startup refuses a stale or missing explainer.

## Verification

- **Part 06 re-check** (fresh clone, after `uv run heatwave-train run` reproduced every bundle's SHA-256 under a new run id):
  - `heatwave-registry verify`: all ok, including "production explainer … matches and reproduces";
  - `heatwave-explain verify`: ok, *after* the fix (before it: "No explainer at …/explainers/xgboost-20261006T092518Z-fe520a");
  - `heatwave-explain show`: additivity max error 2.19e-06; 7/7 sanity checks pass; p50 27.56 / p95 45.42 ms;
  - `uv run pytest` (whole repo): 158 passed before Part 07, with the production-model tests now running instead of skipping.
- `uv run pytest`: **250 passed** (158 ML + 92 backend). Backend coverage by area:
  - **predict:** contract fields, GET parity, peak ties, window, forecast cache and expiry, client conditions and imputation flags, 10 invalid-input cases, unknown region, upstream 502/503, missing-day forecast, model failure with no leaks, latest per region, rate limit;
  - **alerts:** the 401 gate, draft → ready → issued on one record, lock after issue, partial delivery failure (fail + crash), idempotent replay and conflict, filters/paging, 9 invalid inputs, prediction links, rate limit;
  - **auth:** hashing, token signature and expiry, login/me/logout revocation, non-enumerating failures, no password echo, deactivated user, login rate limit, the `AUTH_REQUIRED_FOR_READS` switch;
  - **weather/analytics:** per-region error isolation, all-fail 503, distribution and monthly events with supersession, trend preference and IMD thresholds, model performance, invalid queries;
  - **conventions:** envelope on 404/405/400, 500 without a trace and with the request id, X-Request-ID echo, CORS allow/deny, structured log with risk class and no token, fail-fast startup, missing registry names the fix, production secret refusal, notifier modes, settings validation, migrations (once, FK and CHECK enforced, edited migration refused, failed migration rolled back);
  - **actions and CLI:** class and factor rules, determinism, 5 broken-config refusals, CLI migrate/create-user/set-password, OpenAPI drift.
- **Real model through the API** (`test_production_model.py`):
  - the service serves the registry's production version, with matching metrics;
  - an extreme day comes back SEVERE, with a temperature factor on top, |share| summing to 100, additivity intact through the API, and GET parity;
  - `POST /predict` for 3 days measured **p50 99.5 ms / p95 114.5 ms** through the app (budget 500 ms).
- **Live, over HTTP** (`uvicorn` on :8765, real model, **real Open-Meteo forecast**, temp DB):
  - readiness reported model `xgboost-20260928T100821Z-0bde51` and explainer `…+shap.2154641e`;
  - `POST /predict` for Mumbai returned 7–9 Oct, all NORMAL, peak 8 Oct (35.9 °C, +4.6 °C). That matches the IMD rule: the departure is reached but Tmax is under the 37 °C coastal minimum, and the explanation shows Maximum Temperature as the top risk-*lowering* factor;
  - `GET /weather` returned all 5 regions live;
  - alerts: no token gave 401; the draft got `HW-2026-0001` with channels READY; a double submit replayed it (200); issuing with `NOTIFICATIONS_MOCK_FAIL_CHANNELS=EMERGENCY_SERVICES` gave 2 NOTIFIED + 1 FAILED, plus a warning; an edit after issue gave `ALERT_ALREADY_ISSUED`;
  - analytics returned the model performance (P 0.85239 / R 0.91447 / F1 0.88088 / conf 0.97); logout made the token `TOKEN_REVOKED`;
  - the log has JSON request lines, and 0 occurrences of the token or password.
- **Fail-fast:** `MODEL_VERSION=xgboost-does-not-exist uvicorn …` exited with code 3 ("startup failed …: MODEL_VERSION=… is not a registered model"), and never reported startup complete.
- `uv run heatwave-api check` printed: ok, with the model, explainer, database, 5 regions and mock notifications.
- `uv run pre-commit run --files <changed files>`: every hook passes. The two frontend hooks were skipped (`SKIP=frontend-prettier,frontend-eslint`): there is no `node_modules` on this machine, and the only frontend change is one paragraph in `frontend/README.md`.
  - detect-secrets first flagged two test passwords. One now uses the shared `PASSWORD` constant, and the other carries the repo's `pragma: allowlist secret`.
  - A repo-wide `ruff format .` had also rewritten Python snippets inside the vendored `.claude/skills/*.md`. Those changes were reverted and are not part of this work.

## Deviations from the plan and issues found

- **Part 06 defect (fixed first, `15f641d`):** the explainer was keyed by `bundle.version`, which breaks on every fresh clone. Details in Log 06 Update.
- **Schema created here, not in Part 08.** Part 07 must persist predictions and alerts, and Part 08 had not started. `0001_initial.sql` follows Part 08 §2–4. One addition is `prediction_runs` (the 1–3 day run) above Part 08's per-day `predictions`; another is `revoked_tokens` for logout. Part 08 keeps the review, the mockup cross-check and the backup plan.
- **Bug found by a test:** "latest per region" first used `MAX(created_at)` with the random run id as tie-break. Two predictions in the same second returned the older one. Fixed with an insertion-ordered `prediction_runs.seq` surrogate key, before the migration was ever committed.
- **Extra endpoints beyond §3:**
  - `GET /predictions/latest` and `GET /predictions/{id}` (Parts 11/12 need stored predictions; "latest per region" is Part 11 §2.3);
  - `GET /alerts/{id}` and `PATCH /alerts/{id}` (needed for the single-record status flow);
  - `GET /model` (§3.5's "dedicated lightweight endpoint");
  - `GET /reference` and readiness `GET /api/v1/health`.
- **Routes are `/api/v1/...`,** not the plan's `/api/...`, per §4's versioning requirement.
- **`POST /predict` returns 201** (it creates a stored run, with `Location`), not 200.
- **Test-module collision:** `ml/tests/conftest.py` and `backend/tests/conftest.py` both resolve as `conftest` in a whole-repo run, so the fakes live in `backend/tests/api_support.py`.
- **Toolchain on this machine:** `uv` was not installed. `uv 0.12.23` was installed with pip under Python 3.14, and it manages the project's 3.13 interpreter from `uv.lock` as before.

## Open items / follow-ups

- **Part 08:**
  - review `0001_initial.sql` against §2–4 and the mockups (Parts 11–14), and add any changes as `0002_*.sql`;
  - document the backup approach;
  - decide on a historical backfill: analytics are empty until predictions accumulate, and no `ACTUAL` snapshots are ingested yet.
- **Part 09:** implement live `Notifier`s (email/SMS), templates, recipients, retries, and possibly background dispatch. `NOTIFICATIONS_MODE=live` is refused at startup until then.
- **Part 15:**
  - settle the per-endpoint auth policy (the `AUTH_REQUIRED_FOR_READS` switch exists), the token TTL and refresh, and region scoping;
  - add the frontend login and session handling.
- **Part 18:**
  - run uvicorn with `--proxy-headers` behind a proxy, or rate limits key on the proxy;
  - set a real `AUTH_SECRET_KEY` (enforced) and production CORS origins;
  - re-measure latency on the serving host;
  - with several workers, the rate limits are per worker.
- Recommended-action wording (`ACT-v1`) should be reviewed by a domain owner. It is config, so no code change is needed.

## Handoff

The API is implemented at `http://localhost:8000/api/v1`, with the contract in `docs/api/README.md` and `docs/api/openapi.json`. To run it on a fresh clone:
1. `uv sync --all-packages`
2. `uv run heatwave-train run` (rebuilds the bundles; reproducible)
3. `uv run heatwave-api create-user …`
4. `uv run uvicorn heatwave_api.main:app --reload`

Parts 10–14 can build against real endpoints now. `POST /predict` with `conditions` works without network access. Every response is `{status, data, error, meta}`. The explanation fields are Part 06's, unchanged, and the metric cards read `inputs`. Part 09 plugs in behind `notifications.Notifier`, and Part 15 behind `deps.current_user`/`reader`. Part 08 owns the schema from `0001_initial.sql` onwards.
