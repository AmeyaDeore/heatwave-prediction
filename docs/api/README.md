# Backend API (Part 07)

The FastAPI service that connects the frontend, the model and explainer, the weather data the pipeline ingests, alerts and the SQLite database ([docs/database](../database/README.md)).

- Base URL (local): `http://localhost:8000`. Every route is under **`/api/v1`**. Interactive OpenAPI docs are served at `/docs`, and the machine-readable contract at `/openapi.json`. Treat `/openapi.json` as the exact schema and this page as the behaviour.
- Code: `backend/src/heatwave_api/`. Tests: `backend/tests/`. Why: [ADR 0006](../decisions/0006-backend-api.md).

```sh
uv run uvicorn heatwave_api.main:app --reload
uv run pytest backend/tests
```

## 1. Conventions

### Response envelope

Every response, success or failure, has the same shape, so the frontend handles errors once.

```json
{ "status": "ok",    "data": { "...": "..." }, "meta": { "request_id": "c2353ec933024868", "api_version": "v1" } }
{ "status": "error", "error": { "kind": "client", "code": "UNKNOWN_REGION", "message": "Unknown region 'atlantis'.", "details": null }, "meta": { "request_id": "…", "api_version": "v1" } }
```

`meta.request_id` is also the `X-Request-ID` response header. A caller may send its own `X-Request-ID`, and it is echoed and logged. Quote it in bug reports: it finds the log line.

### Error taxonomy

| `kind` | Meaning | Statuses | Codes |
|---|---|---|---|
| `client` | The caller sent something wrong | 400, 401, 404, 405, 409, 422, 429 | `BAD_REQUEST`, `VALIDATION_ERROR`, `UNAUTHORIZED`, `NOT_FOUND`, `UNKNOWN_REGION`, `METHOD_NOT_ALLOWED`, `CONFLICT`, `RATE_LIMITED` |
| `upstream` | The weather data we depend on is missing, unreadable or lacks the request | 503 | `WEATHER_DATA_UNAVAILABLE` |
| `internal` | Our model, explainer or code failed | 500, 503 | `PREDICTION_FAILED`, `MODEL_UNAVAILABLE`, `INTERNAL_ERROR` |

Messages are written for the user and never contain stack traces, file paths or submitted values. An unexpected exception becomes a 500 `INTERNAL_ERROR` whose message quotes the request id. The full traceback goes to the log under the same id. Validation errors (422) list `details: [{field, message}]` and never echo the input.

### Validation

- Request bodies are strict: an unknown field is a 422, never ignored. A misspelt `lead_dayz` cannot silently fall back to a default.
- `region_id` must match `^[a-z][a-z0-9_]{1,40}$` and exist in `config/regions.yaml` (otherwise 404 `UNKNOWN_REGION`, before any weather or model work).
- Risk classes are exactly `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`. Startup refuses to run if this differs from `config/risk_classes.yaml`.

### CORS

Origins come from `CORS_ALLOWED_ORIGINS` (default `http://localhost:5173`). Only `GET, POST, PATCH, OPTIONS` and the `Authorization`, `Content-Type` and `X-Request-ID` headers are allowed. `X-Request-ID` and `Retry-After` are exposed to the browser. Any other origin's preflight gets 400.

### Rate limiting

A per-client-IP sliding window, per minute: `POST /predict` **30**, `POST`/`PATCH /alerts` **20**, `POST /auth/login` **10** (`RATE_LIMIT_*_PER_MINUTE`). Over the limit returns 429 `RATE_LIMITED` with `Retry-After` (seconds). The state is per process (§8).

### Authentication

`POST /auth/login` returns a bearer token. Send it as `Authorization: Bearer <token>`. Tokens are HMAC-SHA256 signed with `AUTH_SECRET_KEY` and expire after `AUTH_TOKEN_TTL_MINUTES` (60). Missing, invalid or expired tokens return 401 `UNAUTHORIZED`. Part 15 extends this (real users, roles, region scoping).

| Endpoint | Auth |
|---|---|
| `GET` everything, `POST /predict` | none (read model; the dashboard is a monitoring view) |
| `POST /alerts`, `PATCH /alerts/{id}` | **bearer token required** |
| `POST /auth/login` | none (rate limited) |
| `GET /auth/me` | bearer token |

## 2. Endpoints

### `POST /api/v1/predict`

Score a region's conditions for today or one of the next three days. The backend fetches the conditions itself (§4), so the caller sends only a place and a day.

Request:

| Field | Type | Required | Notes |
|---|---|---|---|
| `region_id` | string | yes | A region id from `GET /regions` |
| `lead_days` | int 0–3 | no, default `0` | 0 = today, 1–3 = the next three days |

Response `data` (`PredictionOut`). The `explanation` object is Part 06's contract (`docs/ml/explainability.md` §3) returned **unchanged**; the rest is added by this service.

| Field | Meaning |
|---|---|
| `prediction_id` | `pred_<16 hex>`. The stored record. Read it back with `GET /predictions/{id}` |
| `created_at` | When the prediction was made (UTC) |
| `region` | `{id, name, district, state, zone, lat, lon}` |
| `forecast_window` | `{valid_date, lead_days, issued_at, horizon_days: 3}`. The day predicted, and when the weather forecast was issued |
| `risk_class`, `confidence`, `probabilities` | The prediction. `confidence` = the predicted class's probability |
| `inputs` | The feature values the model was given, before imputation, `null` where missing: `tmax_c, normal_tmax_c, rh_pct, wind_ms, solar_mj_m2, precip_mm, temp_deviation_c`. The Prediction page's metric cards read these (never recompute client-side) |
| `explanation` | `{target_class, reference_class, quantity, explained, baseline, output, factors[7], summary, model_version, explainer_id}`. Each factor: `{rank, feature, label, unit, value, display_value, imputed, contribution, share_pct, direction}` |
| `recommended_actions` | A list of strings. A deterministic function of `risk_class` and the ranked factors (§3) |
| `actions_version` | The version of the mapping that produced the list |
| `weather` | `{source, issued_at, age_hours, stale}`. `stale` is true when the data is older than `WEATHER_STALE_AFTER_HOURS` (36). It is still served and the UI should say so |

Errors: 404 `UNKNOWN_REGION`; 422 bad body; 429; 503 `WEATHER_DATA_UNAVAILABLE` (no file, malformed file, or no row for this region and day); 500 `PREDICTION_FAILED` (the model could not score the row); 503 `MODEL_UNAVAILABLE` cannot occur at request time, because startup fails first (§5).

### `GET /api/v1/predictions/latest?region_id=&lead_days=0`

The most recent **stored** prediction for a region and lead, with no recomputation. This is what Part 12's "show the latest persisted prediction by default" reads. 404 `NOT_FOUND` if none was made yet. `GET /predictions/{prediction_id}` returns one by id.

### `GET /api/v1/weather?region_id=&lead_days=0`

Conditions for one region, or for every monitored region when `region_id` is omitted (the dashboard and its regional table). Each item: `region`, `date`, `lead_days`, `tmax_c`, `normal_tmax_c`, `temp_deviation_c`, `rh_pct`, `wind_ms`, `solar_mj_m2`, `precip_mm`, and `provenance` (`{source, issued_at, age_hours, stale}`). The normal and the deviation come from the shared feature path (`heatwave_ml.features`), not from this service. Errors: 404, 422, 503 `WEATHER_DATA_UNAVAILABLE`.

### `GET /api/v1/alerts?status=&region_id=&limit=25&offset=0`

`data`: `{alerts: AlertOut[], total, limit, offset}`, newest first. `status` ∈ `DRAFT|READY|ISSUED`. `limit` 1–100.

`AlertOut`:

| Field | Meaning |
|---|---|
| `alert_id` | `HW-<year>-<4-digit sequence>`, e.g. `HW-2026-0001` |
| `status` | `DRAFT`, `READY` or `ISSUED` |
| `severity` | `HEATWAVE` or `SEVERE_HEATWAVE` (an alert at NORMAL is refused) |
| `region` | As above |
| `message` | The public advisory text (10–1000 characters) |
| `prediction_id` | The prediction that justified it, or `null` |
| `channels[]` | Per channel `{channel, label, status, detail, updated_at}`. `status` ∈ `READY` (selected, nothing sent), `PENDING` (dispatch in progress), `NOTIFIED`, `FAILED` (`detail` says why) |
| `delivery_summary` | `{total, notified, failed, pending, all_delivered}` |
| `created_at`, `created_by`, `issued_at`, `updated_at` | `issued_at` is `null` until issued |
| `idempotent_replay` | `true` only on a replayed create (below) |

`GET /alerts/{alert_id}` returns one (404 if unknown). `GET /alert-channels` lists the five channels (`public_mobile`, `government_portal`, `display_boards`, `emergency_services`, `hospitals`) as `{id, label, mechanism}`, read from `config/alert_channels.yaml`. `mechanism` is `sms`, `email` or `in_app` (Part 09).

### `POST /api/v1/alerts` (protected)

| Field | Type | Required | Notes |
|---|---|---|---|
| `client_request_id` | UUID | yes | Generate it once per form. See idempotency below |
| `region_id` | string | yes | |
| `severity` | `HEATWAVE` \| `SEVERE_HEATWAVE` | yes | |
| `message` | string 10–1000 | yes | |
| `channels` | string[] 1–20 | yes | Channel ids. Unknown ones are a 400 listing the valid ids. Duplicates are notified once |
| `status` | `DRAFT` \| `READY` \| `ISSUED` | no, default `DRAFT` | "Save as Draft" sends `DRAFT`. "Issue Warning" sends `ISSUED` |
| `prediction_id` | string | no | Must exist (else 400) |

Returns **201** with the `AlertOut`. A replay returns **200**.

### `PATCH /api/v1/alerts/{alert_id}` (protected)

Any of `severity`, `message`, `channels`, `status`. Edits apply while the alert is `DRAFT` or `READY`. `status` moves it along the flow below. So "Save as Draft" then "Issue Warning" is one record moving through one field, not two endpoints.

```
DRAFT ──► READY ──► ISSUED        DRAFT ──► ISSUED is allowed ("Issue Warning" straight away)
  ◄────────┘                      READY ──► DRAFT is allowed (send back for edits)
```

`ISSUED` is terminal and immutable: a change returns 409 `CONFLICT` ("Create a new alert instead"). Any other transition returns 409.

**Issuing.** The alert is first saved as `ISSUED` with every channel `PENDING`, then handed to the notification service (Part 09, [docs/notifications](../notifications/README.md)), which **delivers in the background**. The response therefore normally shows channels `PENDING`. Each channel's result is written back as it lands, and the alert's `updated_at` moves forward. **The frontend polls `GET /alerts/{id}` while `delivery_summary.pending > 0`** (Part 13). A crash mid-dispatch leaves a truthful record, and PENDING channels are resumed at the next startup. **Partial failure is surfaced, never swallowed:** a channel that fails is stored as `FAILED` with a reason (for example `1 of 2 email recipients failed: ...`), the other channels still go out, and the alert stays issued with `delivery_summary.failed > 0` and `all_delivered: false`. The frontend must show per-channel status, not only the HTTP status. A notifier that raises is treated as that channel `FAILED`, with a generic reason. With `NOTIFICATIONS_DISPATCH=inline` (tests), the response already carries the final statuses.

### `GET /api/v1/alerts/{alert_id}/attempts` (protected)

The delivery audit trail: one entry per attempt, `{channel, mechanism, provider, recipient, attempt, outcome: SUCCESS|TRANSIENT_FAILURE|PERMANENT_FAILURE, detail, provider_ref, started_at, duration_ms}`, oldest first. It is protected because it lists recipients. Returns 404 for an unknown alert.

### `GET /api/v1/advisories?region_id=&since=&limit=20`

Public advisories published by the `in_app` channels (Government Portal, Public Display Boards), newest first: `{alert_id, channel, region_id, severity, title, body, published_at}`. Portal and board clients poll this, using `since` to fetch only new ones. `limit` 1–100.

**Idempotency.** Every create needs a client-generated `client_request_id`. The same id from the same user with the same content returns the original alert (200, `idempotent_replay: true`) and notifies nobody a second time. The same id with different content is a 409. A new id always creates a new alert: repeated identical alerts are never merged on content, because two genuine warnings can look identical.

### `GET /api/v1/analytics?days=30&region_id=`

`days` 1–365. `data`:

| Field | Meaning |
|---|---|
| `temperature_trend[]` | `{date, avg_tmax_c, max_tmax_c, predictions}` per forecast date |
| `events_per_month[]` | `{month: "YYYY-MM", heatwave_events, severe_events}` |
| `risk_distribution` | `{NORMAL, HEATWAVE, SEVERE_HEATWAVE}` counts |
| `predictions_in_period` | How many region-days the figures cover |
| `data_source` | `stored_predictions` (see the limitation below) |
| `model_performance` | Precision / Recall / F1 (macro) and accuracy, per-class scores, mean confidence and calibration error of the **production** model on Part 05's held-out test split, plus `model_version`, `explainer_id`, `labeling_rule_version`, `test_rows` |

`model_performance` is static per deployed model version: taken from the promotion pointer (`ml/registry/production.json`) when the model loads, recorded in the `model_metadata` table at startup, and read from there (Part 08), never recomputed per request.

**Limitation:** the trend, event counts and distribution are computed from stored predictions (one per region-day, the newest wins), so they start empty and fill as predictions are made. Predictions now persist across restarts (Part 08). Longer history can be loaded into `weather_snapshots` (`heatwave-db import-weather`); wiring it into this endpoint is Part 14's. The response shape will not change.

### Auth: `POST /api/v1/auth/login`, `GET /api/v1/auth/me`

Login takes `{username, password}` and returns `{access_token, token_type: "bearer", expires_at, user}`. A wrong password and an unknown user give the same 401 message and take the same time. Locally, APP_ENV `local` or `test` seeds one demo official (`DEMO_USER_USERNAME` / `DEMO_USER_PASSWORD`, defaults in `backend/.env.example`). **No user exists in `staging` or `production`** until Part 15 adds them.

### Reference and health

`GET /api/v1/regions` (from `config/regions.yaml`), `GET /api/v1/alert-channels`.
`GET /health` is liveness: the process is up. `GET /api/v1/health/ready` is readiness: `{ready, model_version, explainer_id, weather_data: ok|stale|unavailable, weather_issued_at}`, with status **503** when not ready, so a probe can act on the status code alone.

## 3. Recommended actions (deterministic mapping)

`config/recommended_actions.yaml` (version `RA-v1`). The base list depends only on the risk class. Extra actions are added when a named feature is among the top *N* ranked factors **and** moves the risk in the stated direction. The same class and factors always give the same list in the same order, and there is no free text. Edit the wording in the file, never in code, and bump `version`.

| Risk class | Base actions |
|---|---|
| `NORMAL` | Continue routine monitoring of the daily forecast |
| `HEATWAVE` | Issue ward-level heat advisory · Activate cooling centres in high-exposure wards · Alert hospitals and health centres to expect heat-related cases · Advise outdoor workers to avoid work between 12:00 and 16:00 |
| `SEVERE_HEATWAVE` | The four above, plus: Brief emergency services and put field response teams on standby · Request public display boards to show the heat warning |

Factor rules: humidity among the top 3 and raising risk (HEATWAVE/SEVERE) adds humid-heat guidance. Wind among the top 3 and lowering risk (NORMAL) adds a monitoring note. Because about 90 % of every explanation is temperature (Part 06), these rarely fire for the current model.

## 4. Weather source decision (Part 07 §2)

**The backend reads the conditions the pipeline already ingested; it never calls Open-Meteo, NASA POWER or IMD itself.**

- The file is `WEATHER_FEATURES_FILE` (default `data/sample/forecast_features.csv`), written by `uv run heatwave-prepare sample` after `heatwave-ingest forecast`. It has today plus three days per region, in canonical units, with `issued_at`.
- Why: one code path fetches and unit-normalises weather (Parts 02/03), the API stays fast and testable offline, and a provider outage shows up as *stale, flagged* data (`weather.stale`) instead of failed requests. The backend also never needs provider credentials.
- The file is re-read whenever its modification time changes, so refreshing it needs no restart.
- The seasonal normal and deviation are computed in the shared `build_features`, from `config/seasonal_normals.csv`, exactly as in training.
- **Freshness:** data older than `WEATHER_STALE_AFTER_HOURS` (36) is served with `stale: true`. Scheduling the ingestion (every few hours) is Part 16/18's job. Until then the committed sample ages, and readiness reports `weather_data: "stale"`.

## 5. Model and explainer lifecycle (Part 07 §5)

- **Loaded once, at startup** (`lifespan`): `load_production_explainer(registry)` loads the model the promotion pointer names and its explainer, then the seasonal normals. Nothing is loaded per request.
- **Fail fast:** a missing pointer, a bundle that isn't the pointer's model, a tampered or stale explainer (built for another model), a library-version mismatch, or an explainer that no longer reproduces its probe all raise `MODEL_UNAVAILABLE` and **the process does not start**. The service never comes up healthy and fails on its first prediction. Outside `local`/`test`, the default `AUTH_SECRET_KEY` also stops startup.
- **Picking up a new production model:** promote it (`heatwave-registry promote`), rebuild its explainer (`heatwave-explain build`), then **restart the service**. Rollback is the same, with `rollback`. There is deliberately no hot-swap. If someone promotes without rebuilding the explainer, the restart fails with "Stale explainer … Rebuild it", which is the intended safety.
- `MODEL_VERSION=production` follows the pointer. Pinning an exact version id is not supported, because the explainer and the pointer must agree: promote instead.
- **Concurrency:** requests run in a thread pool. The SHAP call is serialised with a lock, as SHAP's C extension is not documented as thread-safe. At ~30–50 ms per request that limits one process to roughly 20–30 predictions/second, ample for this project. Scale with more processes if ever needed.

## 6. Logging

One JSON object per line on stderr (`logger` `heatwave_api.access` for requests). Every request logs `request_id`, `method`, `path`, `status`, `latency_ms` and `user_id`. A prediction adds `risk_class`, `region_id` and `lead_days`, and alert writes add `alert_id` and `alert_status`, which is what Parts 14 and 18 need. Client and upstream errors log at WARNING, internal errors at ERROR with the traceback. Startup logs the model and explainer ids.

## 7. Performance

Measured through the full ASGI stack (in-process test client, so no network) on the dev laptop with the real model: `POST /predict` p50 34.8 ms, p95 39.9 ms, max 55 ms over 50 requests, SHAP included. `backend/tests/test_production_model.py` asserts p95 < 500 ms, Part 05's `max_p95_request_ms`. Re-measure on the serving host (Part 18).

## 8. Known limits and open items

- **Persistence is SQLite (Part 08, resolved).** `SqliteRepository` implements the `Repository` protocol; predictions, alerts, deliveries and users survive restarts. `UNIQUE (created_by, client_request_id)` makes idempotency atomic. Schema, migrations and backups: [docs/database/README.md](../database/README.md). One API process only (SQLite's single writer).
- **Users and roles are Part 15's.** Users are stored in the `users` table, but only the seeded local demo official exists. There is no refresh, revocation or region scoping.
- **Notifications run in mock mode by default** (Part 09): nothing is sent until `NOTIFICATIONS_MODE=live` with provider credentials. `NOTIFIED` means "accepted by the provider", because delivery-receipt webhooks are not consumed yet (docs/notifications §10).
- **Rate limits are per process and per IP.** Behind several workers or a proxy, the limit multiplies or all clients share one IP. Deploying behind a proxy needs `X-Forwarded-For` handling (Part 18).
- **Analytics history** comes from stored predictions until Part 14 reads `weather_snapshots` (§2).
- There is no endpoint yet for "latest risk for every region" in one call: the dashboard can call `GET /weather` for conditions and `POST /predict` per region, or Part 11 may ask for a batch endpoint. The batch cost is known: ~0.34 s for 15 rows (Part 06).

## 9. Handoff (Part 07 plan §9)

> API base URL: `http://localhost:8000/api/v1` (local). Contracts: this page and `/openapi.json`. Auth: `POST /alerts` and `PATCH /alerts/{id}` need a bearer token, everything else is open (§1). **Part 08 owner:** implement `Repository` (`backend/src/heatwave_api/repositories.py`) on SQLite, matching the fields in `schemas.py` (`prediction_factors` rows come from `explanation.factors`; store `model_version` and `explainer_id`; `alert_channel_deliveries` holds `channels[]`; alert ids are `HW-<year>-<seq>`). **Part 10 (frontend):** build against the contract above, or against `data/sample/` responses, before every piece is persisted.
