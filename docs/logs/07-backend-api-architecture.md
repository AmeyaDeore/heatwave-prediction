# Log 07 — Backend API architecture

| | |
|---|---|
| Plan | [Implementation/07-backend-api-architecture.md](../../Implementation/07-backend-api-architecture.md) |
| Status | Complete against the plan's checklist, with three seams left for later parts: **persistence is in memory (Part 08), notifications are mocked (Part 09), users are one seeded demo account (Part 15)** |
| Date | 2026-09-29 |
| Branch / commits | `part-07/backend-api` (from `main` at `e8bb826`). Not committed or pushed yet |
| Tests | 80 new in `backend/tests/` (81 with the existing health test), 237 total passing |

## Summary

Part 07 added the `/api/v1` service on top of Parts 03, 05 and 06: `POST /predict` returns the Part 06 explanation unchanged with the input values, forecast window and recommended actions; `GET /weather`, `/alerts`, `/analytics`, `/regions`, `/alert-channels`, health and auth complete the inventory; and `POST`/`PATCH /alerts` are behind a bearer token. The model and explainer load at startup and stop the process if anything is missing, stale or tampered with. It was exercised end to end on the real production model (`xgboost-20260928T100821Z-0bde51`) through a live `uvicorn` process.

## What was built

| Path | Role |
|---|---|
| `backend/src/heatwave_api/app.py` | `create_app()` factory: lifespan startup (fail fast), request-id + structured access-log middleware, error handlers, CORS, `/health` |
| `routes.py` | Every `/api/v1` endpoint |
| `schemas.py`, `envelope.py`, `errors.py` | Contracts, the one response envelope, the client / upstream / internal taxonomy |
| `predictor.py` | `ProductionPredictor`: loads model + explainer + normals once; `predict()` and `inputs()` go through the shared `build_features` |
| `weather.py` | `PipelineWeatherSource`: reads the pipeline's forecast CSV (re-read on mtime change), maps problems to `UpstreamUnavailable` |
| `services.py` | Prediction, weather and analytics assembly; model performance from the promotion pointer |
| `alerts.py` | The DRAFT → READY → ISSUED flow, dispatch with per-channel results, idempotent create |
| `auth.py`, `ratelimit.py` | scrypt + HMAC bearer tokens, sliding-window limits |
| `repositories.py`, `notifier.py` | Protocols for Part 08 / Part 09, with in-memory and mock implementations |
| `catalog.py` | Loads regions, channels, risk classes and recommended actions from `config/` and validates them at startup |
| `config/alert_channels.yaml`, `config/recommended_actions.yaml` | New shared config (channel ids and labels; the action mapping, version `RA-v1`) |
| `backend/tests/` | `fakes.py` + `conftest.py` (fake model, weather, notifier) and six test modules |
| `docs/api/README.md`, `docs/decisions/0006-backend-api.md` | Contract and decisions |

**Dependency change:** `heatwave-ml` (workspace) and `pyyaml` added to `backend/pyproject.toml`, so `uv sync --package heatwave-api` now installs the ML stack (the model unpickles in the API process). `uv.lock` gained 4 lines.
**Config/env:** `backend/.env.example` and `config.py` gained the weather file, staleness, rate limits, demo-user and config-file paths. `docs/local-dev-runbook.md` step 6 now needs the trained bundles first.

## Key decisions and why

See [ADR 0006](../decisions/0006-backend-api.md) for the full table. The ones that matter most:

- **Weather:** the backend reads what the pipeline ingested and never calls a provider. Outages become flagged-stale data instead of failed requests. This is the decision the plan asked to be documented.
- **`/predict` takes `region_id` + `lead_days`**, not raw features, so a client cannot bypass the shared feature path.
- **Routes are `/api/v1/...`**, the plan's paths with a version segment.
- **One alert record, one `status` field**, edited with `PATCH`. `ISSUED` is immutable. Issuing saves every channel as PENDING before dispatching. A failed channel is FAILED with a reason and the response is still 201 with `delivery_summary`.
- **Idempotency:** a client `client_request_id`; replay returns the original with 200; same id and different content is 409.
- **Interfaces for the parallel parts** rather than guessing at Part 08's schema.

## Verification

- `uv run pytest`: **237 passed** (157 before this part). `uv run ruff check .` and `ruff format --check .` clean. `uv run pre-commit run --all-files`: all hooks pass.
- The 80 new tests cover, against fakes: the envelope, request-id echo, 404/405/422 shapes and no input echo; the taxonomy's statuses and kinds; a 500 with no traceback or internal detail; the full prediction contract and SHAP factors in the same response; `lead_days` bounds; unknown region before any model call; upstream and model failures; stale flag; stored and latest predictions; deterministic actions (and the factor rules firing or not); rate limiting on predict, alert writes and login; every alert transition, edit, immutability, partial and raising-notifier failures, idempotent replay and conflict, validation, pagination; token expiry and tampering; equal answers for wrong password and unknown user; startup failure on a missing model, on the default secret outside local, and no demo user in staging; the file-backed weather source (blank values, refresh, malformed, missing).
- 6 tests run the **real** production model, explainer and pipeline weather file (skipped on a fresh clone without bundles): the service starts and is ready, a prediction has all 7 ranked factors that sum to ~100 % share, `baseline + Σ contributions = output`, weather deviation equals tmax − normal, analytics reports F1 0.88088, and p95 latency < 500 ms.
- **Live run** (`uvicorn heatwave_api.main:app`): `/health` 200; login then `POST /alerts` with `status: ISSUED` created `HW-2026-0001`, both channels NOTIFIED; the same call without a token 401; CORS preflight from `http://localhost:5173` allowed and from `http://evil.example` refused (400); `/openapi.json` lists the 13 routes.
- **Latency** (in-process client, real model, 50 requests over 5 regions × 4 leads): p50 34.8 ms, p95 39.9 ms, max 55 ms (Part 05 budget 500 ms). Real prediction for Mumbai, 1 day ahead: NORMAL, confidence 0.9997, actions `["Continue routine monitoring of the daily forecast"]`.

## Deviations from the plan and issues found

- **Persistence, notifications and users are seams, not the real thing** (the plan lists them as dependencies on 08, 09, 15). The API depends on Protocols and ships in-memory / mock / demo implementations. Consequence: **predictions and alerts vanish on restart, so the service must not be deployed until Part 08 lands.** This is stated in `docs/api/README.md` §8, the ADR and `backend/README.md`.
- **Analytics history is thin:** trend, monthly counts and distribution come from stored predictions, so they start empty. Model performance is real. A weather-history source arrives with Parts 08/14.
- **No batch "all regions" prediction endpoint.** The dashboard can call `/weather` plus `/predict` per region. It is not in Part 07's inventory, so it was left out and flagged.
- **`MODEL_VERSION` pinning is refused** (only `production`), because the explainer and the pointer must agree. The setting already existed from Part 01.
- **Committed weather sample is dated 2026-09-28**, so it will show `stale` after 36 hours until `heatwave-ingest forecast && heatwave-prepare sample` is run again. Readiness reports it.
- **Rate limiting is per process and per IP.** Fine for one node, wrong behind a proxy.
- **Tooling issues while building:** the shell tool cannot take a heredoc with an odd number of apostrophes (three files were written with the editor instead), and one scripted edit replaced the wrong `def predict` in `predictor.py` and was rewritten. The final files are covered by the tests above.

## Open items / follow-ups

- **Part 08:** implement `Repository` on SQLite (see the handoff), with a unique key on `(created_by, client_request_id)` and `prediction_factors` from `explanation.factors`; then swap it into `build_context` and delete the "in memory" warnings. Add the migration that seeds `regions` from `config/regions.yaml`.
- **Part 09:** implement `Notifier.send` (return FAILED with a reason, never raise); select it by `NOTIFICATIONS_MODE`.
- **Part 15:** real users behind `UserStore`; roles, region scoping, revocation. Login rate limiting is already in.
- **Part 16/18:** schedule the forecast ingestion, proxy-aware client IPs for rate limiting, a real `AUTH_SECRET_KEY`, re-measure latency on the serving host, decide the "latest risk for every region" call for the dashboard (Part 11).
- **Part 12/13:** the frontend must show per-channel delivery status, not only the HTTP status of an issue call. `weather.stale` should be shown to the user.

## Handoff

API on `http://localhost:8000/api/v1`. Contract: [docs/api/README.md](../api/README.md) and `/openapi.json`. Writes (`POST`/`PATCH /alerts`) need `Authorization: Bearer <token>` from `POST /auth/login` (local demo user `official` / `demo-official-local`). `POST /predict` carries the Part 06 explanation unchanged (all 7 ranked factors), `inputs`, `forecast_window`, `recommended_actions` and weather provenance. Part 08's owner implements `Repository` from `backend/src/heatwave_api/repositories.py` to persist predictions (with `model_version` and `explainer_id`), factors and alerts. Part 10 can build against the documented contract now.
