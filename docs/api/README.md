# API contract — Heatwave Early Warning API (v1)

The request/response contract for every endpoint (Part 07 §3), and the conventions they share (§4–§7). The machine-readable schema is [`openapi.json`](openapi.json), generated from the code's Pydantic models (`uv run heatwave-api openapi`). A test fails if it is stale. A running server serves the same schema interactively at `/docs`.

Base URL: `http://localhost:8000/api/v1` locally (the frontend's `VITE_API_BASE_URL` + `/api/v1`). Decisions and alternatives: [ADR 0006](../decisions/0006-backend-api.md).

## Contents

1. [Conventions](#1-conventions): envelope, versioning, validation, errors, auth, CORS, rate limits, idempotency, logging
2. [Endpoint summary](#2-endpoint-summary)
3. [Predictions](#3-predictions): `POST /predict`, `GET /predictions/latest`, `GET /predictions/{id}`
4. [Weather](#4-weather): `GET /weather`
5. [Alerts](#5-alerts): `GET /alerts`, `GET /alerts/{id}`, `POST /alerts`, `PATCH /alerts/{id}`
6. [Analytics](#6-analytics): `GET /analytics`, `GET /model`
7. [Auth](#7-auth): `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
8. [Service](#8-service): `GET /health`, `GET /reference`, `GET /health` (liveness)
9. [Model lifecycle](#9-model-lifecycle-and-startup)

## 1. Conventions

### 1.1 Response envelope

Every response under `/api/v1`, success or failure, has the same four keys:

```json
{ "status": "success", "data": { "...": "..." }, "error": null,
  "meta": { "request_id": "5867c791846043419c6e0054c6dcf372", "api_version": "v1",
            "warnings": [], "idempotent_replay": null } }
```

```json
{ "status": "error", "data": null,
  "error": { "code": "UNKNOWN_REGION", "category": "client",
             "message": "Unknown region 'atlantis'.",
             "details": { "known_regions": ["andheri", "colaba", "dharavi", "kurla", "mumbai"] } },
  "meta": { "request_id": "…", "api_version": "v1", "warnings": [], "idempotent_replay": null } }
```

- Branch on `status`. Show `error.message` to the user. Branch on `error.code` in code.
- `meta.warnings` lists non-fatal problems on a successful response, such as a channel that failed to deliver, or a region whose weather could not be fetched. Show them; never drop them.
- `meta.request_id` is also sent as the `X-Request-ID` header. A client may send its own `X-Request-ID` (8–64 characters of `[A-Za-z0-9._-]`), and it is echoed and used in the logs. Quote it in bug reports.
- Timestamps are ISO 8601 in UTC (`2026-10-06T09:52:23Z`), except `issued_at` of a forecast, which keeps India's offset (`+05:30`). Dates are `YYYY-MM-DD`, as calendar dates in India.

### 1.2 Versioning

All routes live under `/api/v1`. A breaking change (renaming or removing a field, changing a type or a meaning) means `/api/v2`, served alongside v1 until the frontend moves. Adding a field or an endpoint is not breaking, so clients must ignore unknown fields. The un-versioned `/health` is the process liveness probe for supervisors (Part 18).

### 1.3 Validation

Every input is validated against its schema before the model or the database is touched (Pydantic models in `backend/src/heatwave_api/schemas.py`):

- Request bodies reject unknown fields. A typo is a `422`, never silently ignored.
- Strings are trimmed. Ranges are physical (`tmax_c` −20…60 °C, `rh_pct` 0…100, and so on).
- Nothing is silently defaulted. One case looks like a default and is not: an omitted optional weather value is imputed by the model's fitted imputer, and every place that value appears says `"imputed": true`.
- A validation failure is `422 VALIDATION_ERROR`, with `details` as a list of `{loc, msg, type}`. Submitted values are never echoed back, because they can include a password.

### 1.4 Errors

| Category | When | Status codes | Examples (`error.code`) |
|---|---|---|---|
| `client` | The request is wrong | 400, 404, 405, 409, 422, 429 | `VALIDATION_ERROR`, `UNKNOWN_REGION`, `PREDICTION_NOT_FOUND`, `ALERT_NOT_FOUND`, `UNKNOWN_PREDICTION`, `PREDICTION_REGION_MISMATCH`, `ALERT_ALREADY_ISSUED`, `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`, `NOT_FOUND`, `METHOD_NOT_ALLOWED` |
| `auth` | No session, or a bad one | 401, 403 | `UNAUTHENTICATED`, `INVALID_CREDENTIALS`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, `TOKEN_REVOKED` |
| `upstream` | The weather source failed. Not our bug, and retrying later may help | 502, 503 | `WEATHER_SOURCE_ERROR` (502: an error or unusable data), `WEATHER_SOURCE_UNAVAILABLE` (503: unreachable after retries) |
| `internal` | Our model, database or code failed | 500, 503 | `PREDICTION_FAILED`, `INTERNAL_ERROR`, `SERVICE_NOT_READY` |

Messages never contain a stack trace, SQL, or a file path. Those go to the log under the same request id. On partial failures:

- An alert whose delivery fails on some channels is still a `2xx`. Each channel carries its own status, the failures are listed in `meta.warnings`, and the record keeps them (§5).
- `GET /weather` for all regions returns the regions it could fetch, and puts an `error` object on each region it could not. Only when every region fails is the whole response an upstream error.

### 1.5 Authentication and authorization

Sign in with `POST /auth/login`, then send `Authorization: Bearer <access_token>`. Tokens are signed (HS256 JWT) and expire after `AUTH_TOKEN_TTL_MINUTES` (default 60). `POST /auth/logout` revokes the token. The check is enforced on the server, so hiding a button in the UI is only a convenience.

| Endpoint | Auth |
|---|---|
| `POST /alerts`, `PATCH /alerts/{id}`, `POST /auth/logout`, `GET /auth/me` | **Always required** |
| Every `GET` except health, plus `POST /predict` | Open by default. Required when `AUTH_REQUIRED_FOR_READS=true` (the final choice belongs to Part 15) |
| `POST /auth/login`, `GET /health`, `GET /api/v1/health` | Never |

`POST /predict` counts as a read: it computes and records a prediction, but it publishes nothing and notifies no one. Every consequential write is an alert write. On `401`, the frontend redirects to login. `TOKEN_EXPIRED` means "your session timed out", and `INVALID_CREDENTIALS` always gets the same message, whether the username or the password was wrong.

### 1.6 CORS

Only the origins in `CORS_ALLOWED_ORIGINS` are allowed (default `http://localhost:5173`; production adds its own, Part 18). The allowed methods are `GET, POST, PATCH, OPTIONS`, and the allowed request headers are `Authorization, Content-Type, X-Request-ID`. The exposed response headers are `X-Request-ID, Retry-After, Location`. There are no cookies, so CORS runs without credentials.

### 1.7 Rate limiting

Requests are counted in a fixed window, per client address, per process:

| Bucket | Endpoints | Default |
|---|---|---|
| `predict` | `POST /predict` | `RATE_LIMIT_PREDICT=30/minute` |
| `alert_writes` | `POST /alerts`, `PATCH /alerts/{id}` | `RATE_LIMIT_ALERT_WRITES=10/minute` |
| `login` | `POST /auth/login` | `RATE_LIMIT_LOGIN=5/minute` (brute-force protection, Part 15 §7) |

Going over the limit returns `429 RATE_LIMITED`, with a `Retry-After` header and `details.retry_after_s`. The dashboard should read stored predictions (`GET /predictions/latest`) when it polls, and call `POST /predict` only when the user asks for a fresh prediction.

### 1.8 Idempotency (alerts)

A repeated `POST /alerts` creates a new alert each time, unless both requests carry the same `client_request_id`. The UI generates one UUID per form submission and reuses it on retries:

- The same id with the same body returns the original alert: **200** instead of 201, `meta.idempotent_replay: true`, and nothing is created or dispatched a second time.
- The same id with a different body returns `409 IDEMPOTENCY_CONFLICT`.

### 1.9 Logging

There is one JSON line per request, with the request id, method, path, status, `latency_ms` and client. Predictions add `region_id`, `risk_class`, `prediction_id`, `model_version` and `weather_source`, and authenticated calls add `user`. Every alert delivery attempt logs its channel and outcome. Headers and bodies are never logged, so tokens and passwords cannot leak.

## 2. Endpoint summary

| Method & path | Purpose | Success | Auth |
|---|---|---|---|
| `POST /predict` | Predict and explain the next 1–3 days for a region; stored | 201 `Prediction` | open* |
| `GET /predictions/latest?region_id=` | The latest stored prediction per region (dashboard) | 200 `{items, missing_regions}` | open* |
| `GET /predictions/{prediction_id}` | One stored prediction, exactly as `POST /predict` returned it | 200 `Prediction` | open* |
| `GET /weather?region_id=` | Today's conditions per region, plus each region's latest prediction summary | 200 `{items}` | open* |
| `GET /alerts?status=&region_id=&limit=&offset=` | Alerts, newest first | 200 `{items, total, limit, offset}` | open* |
| `GET /alerts/{alert_id}` | One alert, with per-channel delivery status | 200 `Alert` | open* |
| `POST /alerts` | Create an alert (`DRAFT`/`READY`/`ISSUED`) | 201 `Alert` (200 on replay) | **required** |
| `PATCH /alerts/{alert_id}` | Edit a draft, or change status (`ISSUED` dispatches it) | 200 `Alert` | **required** |
| `GET /analytics?region_id=&period=&end_date=&months=` | Trend, distribution, monthly events, model performance | 200 `Analytics` | open* |
| `GET /model` | The deployed model and its Part 05 test metrics | 200 | open* |
| `GET /reference` | Regions, vocabularies, labels | 200 | open* |
| `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` | Session | 200 | login: none |
| `GET /health` (under `/api/v1`) | Readiness: model and explainer loaded, database reachable | 200 | none |

\* Open unless `AUTH_REQUIRED_FOR_READS=true`.

## 3. Predictions

### 3.1 `POST /predict`

**Weather source decision (Part 07 §2).** The backend fetches the forecast itself. It calls Part 02's Open-Meteo adapter, runs Part 03's `build_features`, and stores the readings in `weather_snapshots`. A stored forecast younger than `WEATHER_CACHE_MINUTES` (60) is reused. The frontend sends only a region. A caller may supply the weather instead (`conditions`), for what-if analysis or offline use.

**Request.**

| Field | Type | Required | Notes |
|---|---|---|---|
| `region_id` | string | yes | An id from `GET /reference` (`mumbai`, `kurla`, …) |
| `forecast_days` | int 1–3 | no (default 3) | Predict lead days 1..N (tomorrow onwards). Not allowed with `conditions` |
| `conditions` | array of 1–3 | no | One entry per date: `date` (required), `tmax_c` (required, °C), `rh_pct`, `wind_ms`, `wind_height_m` (required with `wind_ms`; 10 for most stations, 2 already at the model's height), `solar_mj_m2` (MJ/m²/day), `precip_mm` (mm/day). An omitted optional value is imputed and flagged |

```json
{ "region_id": "mumbai" }
{ "region_id": "andheri", "conditions": [ { "date": "2026-05-11", "tmax_c": 42.0, "rh_pct": 40,
  "wind_ms": 2.0, "wind_height_m": 10, "solar_mj_m2": 25, "precip_mm": 0 } ] }
```

**Response `201`** (`Location: /api/v1/predictions/{prediction_id}`). A prediction is a **run**: every day of the window, each with its own risk class and full SHAP explanation. The top-level fields are those of the **peak day**, chosen by the highest risk class, then the higher 1 − P(NORMAL), then the earlier date.

| Field | Meaning |
|---|---|
| `prediction_id` | 32-hex id of the run. Cite it on an alert (`prediction_id`) |
| `region` | `{id, name, district, state, zone, lat, lon}` |
| `created_at` | When the prediction was made |
| `forecast_window` | `{start, end, days, label}`. `label` is `"Next 3 days"` / `"Next day"` for forecast runs, or a date range for `conditions` runs |
| `peak_date` | The day the top-level fields describe |
| `risk_class`, `risk_label` | `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`, and its display name |
| `confidence` | P(`risk_class`): the banner's "91% RISK" |
| `probabilities` | `{NORMAL, HEATWAVE, SEVERE_HEATWAVE}` |
| `inputs` | Per feature (all 7, keyed by internal name): `{label, unit, value, display_value, imputed}`. These are the values the model used, after imputation. The metric cards read `tmax_c`, `rh_pct`, `wind_ms` (at 2 m) and `temp_deviation_c` from here |
| `explanation` | **The Part 06 contract, unchanged** ([explainability.md §3](../ml/explainability.md)): `target_class`, `reference_class`, `quantity`, `explained`, `baseline`, `output`, `factors[]` (all 7, ranked: `rank, feature, label, unit, value, display_value, imputed, contribution, share_pct, direction`), `summary`, `model_version`, `explainer_id`. Bars use `share_pct` and `direction` directly |
| `recommended_actions` | `[{rank, code, text, reason}]`: the "ACT NOW" list. A deterministic mapping from the risk class plus the SHAP factors ([`config/recommended_actions.yaml`](../../config/recommended_actions.yaml)): the class's fixed actions, then any factor rule that matches |
| `actions_version` | The version of that mapping (`ACT-v1`) |
| `daily[]` | Every day: `{date, lead_days, risk_class, risk_label, confidence, probabilities, inputs, explanation}` |
| `source` | `{weather: "open_meteo_forecast" \| "client", issued_at, fetched_at}` |
| `model` | `{model_version, explainer_id}` |

Example (live forecast, abridged):

```json
{ "prediction_id": "0769d2f95b8e4294a31ea3a4a091ef8d",
  "region": { "id": "mumbai", "name": "Mumbai", "district": "Mumbai City", "...": "..." },
  "forecast_window": { "start": "2026-10-07", "end": "2026-10-09", "days": 3, "label": "Next 3 days" },
  "peak_date": "2026-10-08", "risk_class": "NORMAL", "risk_label": "Normal", "confidence": 0.9857,
  "inputs": { "tmax_c": { "label": "Maximum Temperature", "unit": "°C", "value": 35.9,
                          "display_value": "35.9 °C", "imputed": false }, "...": "..." },
  "explanation": { "factors": [ { "rank": 1, "feature": "tmax_c", "label": "Maximum Temperature",
       "display_value": "35.9 °C", "share_pct": -48.4,
       "direction": "decreases_risk", "...": "..." }, "..." ],
     "summary": "The model predicts Normal conditions (99% probability). The main factor keeping the risk low is Maximum Temperature (35.9 °C). Temperature Deviation (+4.6 °C) and Seasonal Normal Temperature (31.4 °C) raised the risk somewhat.",
     "model_version": "xgboost-20260928T100821Z-0bde51",
     "explainer_id": "xgboost-20260928T100821Z-0bde51+shap.2154641e", "...": "..." },
  "recommended_actions": [ { "rank": 1, "code": "ROUTINE_MONITORING",
       "text": "Continue routine monitoring of the 1-3 day heat forecast", "reason": "Normal predicted" }, "..." ],
  "actions_version": "ACT-v1", "daily": [ "…3 days…" ],
  "source": { "weather": "open_meteo_forecast", "issued_at": "2026-10-06T15:22:23+05:30",
              "fetched_at": "2026-10-06T09:52:23Z" },
  "model": { "model_version": "xgboost-20260928T100821Z-0bde51",
             "explainer_id": "xgboost-20260928T100821Z-0bde51+shap.2154641e" } }
```

**Errors.**

| Case | Status | `error.code` |
|---|---|---|
| Unknown region | 404 | `UNKNOWN_REGION` (`details.known_regions`) |
| Invalid or missing input: range, unknown field, `wind_ms` without `wind_height_m`, both `forecast_days` and `conditions`, duplicate dates | 422 | `VALIDATION_ERROR` |
| Forecast source unreachable after retries (timeout 10 s, 2 attempts) | 503 | `WEATHER_SOURCE_UNAVAILABLE` |
| Forecast source error, or a forecast missing a day or its Tmax | 502 | `WEATHER_SOURCE_ERROR` |
| Model/explainer failure during the request | 500 | `PREDICTION_FAILED` |
| Model/explainer not loaded | n/a | The service does not start at all (§9) |
| Over the rate limit | 429 | `RATE_LIMITED` |

Nothing is stored for a failed request.

### 3.2 `GET /predictions/latest?region_id=`

`data`: `{items: [Prediction…], missing_regions: [region_id…]}`. Each monitored region's most recent run (in insertion order), or only `region_id`'s. Regions with no prediction yet are in `missing_regions`. One call feeds the dashboard's cards, regional table, "why" panel and actions. `404 UNKNOWN_REGION` for a bad `region_id`.

### 3.3 `GET /predictions/{prediction_id}`

A stored run, **byte-identical** to the `POST /predict` response that created it (both are built by one function from the stored rows). `404 PREDICTION_NOT_FOUND`, or `422` for a malformed id.

## 4. Weather

### `GET /weather?region_id=`

`data.items[]`, one per monitored region (or only `region_id`):

| Field | Meaning |
|---|---|
| `region` | As above |
| `current` | Today's best reading, or `null`: an observation (`kind: ACTUAL`) when one exists, otherwise the newest forecast for today (`kind: FORECAST`, lead 0). Fields: `date, kind, source, issued_at, fetched_at, tmax_c, normal_tmax_c, temp_deviation_c, rh_pct, wind_ms` (at 2 m), `solar_mj_m2, precip_mm`, and `display` (formatted strings, e.g. `"+2.2 °C"`, for the "+3.0° above seasonal normal" sub-label) |
| `latest_prediction` | `{prediction_id, created_at, forecast_window, peak_date, risk_class, risk_label, confidence}`, or `null`. The regional table's Risk column |
| `error` | `null`, or an error object when this region's forecast could not be fetched. Also repeated in `meta.warnings` |

This endpoint refreshes the stored forecast when it is stale, so it can return 502/503 when every requested region fails. `404 UNKNOWN_REGION` for a bad `region_id`.

## 5. Alerts

**Status flow (Part 07 §3.4).** A single record moves through an explicit `status` field. "Save as Draft" and "Issue Warning" write the same record:

```
DRAFT ⇄ READY ──► ISSUED        (DRAFT ──► ISSUED directly is allowed too; ISSUED is final)
```

Only the transition into `ISSUED` dispatches anything, so saving or editing a draft never notifies anyone. Delivery status per channel goes `READY` (selected, not sent) → `PENDING` (issuing) → `NOTIFIED` or `FAILED`. Each channel is dispatched on its own and its outcome is committed as it happens, so one channel failing never blocks the others or hides behind a "success". Dispatch is synchronous for now, using the mock notifier, so the issue response already carries the final statuses. Part 09 may move live providers to a background task. The frontend polls `GET /alerts/{id}` either way.

Channels (the code, then its `label`): `PUBLIC_MOBILE_ALERT` (Public Mobile Alert), `GOVERNMENT_PORTAL`, `PUBLIC_DISPLAY_BOARDS`, `EMERGENCY_SERVICES`, `HOSPITALS_HEALTH_CENTRES` (Hospitals & Health Centres).

**`Alert` object.**

| Field | Meaning |
|---|---|
| `alert_id` | `HW-<year>-<seq>`, e.g. `HW-2026-0007`. The sequence restarts each year (India's calendar year) |
| `status` | `DRAFT` / `READY` / `ISSUED` |
| `severity`, `severity_label` | A risk class and its display name |
| `region` | As above |
| `message` | The public advisory text (1–1000 characters; SMS length rules belong to Part 09) |
| `channels[]` | `{channel, label, status, attempts, last_error, updated_at}` |
| `delivery_summary` | Counts per delivery status: `{READY, PENDING, NOTIFIED, FAILED}` |
| `prediction_id` | The prediction that justified the alert, or `null` |
| `created_at`, `created_by` | `{username, display_name}` |
| `updated_at` | |
| `issued_at`, `issued_by` | `null` until issued |

### 5.1 `GET /alerts?status=&region_id=&limit=50&offset=0`

`data`: `{items: [Alert…], total, limit, offset}`, newest first. `limit` is 1–100. Bad filter values are `422`.

### 5.2 `GET /alerts/{alert_id}`

One alert. `404 ALERT_NOT_FOUND`.

### 5.3 `POST /alerts` (auth required)

| Field | Type | Required | Notes |
|---|---|---|---|
| `client_request_id` | UUID | yes | §1.8 |
| `region_id` | string | yes | |
| `severity` | risk class | yes | Defaults in the UI from the prediction context (Part 13) |
| `message` | string 1–1000 | yes | |
| `channels` | 1–5 distinct channel codes | yes | |
| `status` | `DRAFT` (default) / `READY` / `ISSUED` | no | `ISSUED` issues and dispatches immediately |
| `prediction_id` | string | no | Must exist, and must be for the same region |

`201` with the `Alert` (`Location: /api/v1/alerts/{alert_id}`), or `200` on a replay. Errors: `401`, `404 UNKNOWN_REGION`, `409 IDEMPOTENCY_CONFLICT`, `422 VALIDATION_ERROR` / `UNKNOWN_PREDICTION` / `PREDICTION_REGION_MISMATCH`, `429`.

### 5.4 `PATCH /alerts/{alert_id}` (auth required)

Any subset of `region_id, severity, message, channels, status, prediction_id`, and at least one of them. Changing `channels` replaces the selection, and every channel goes back to `READY`. `status: "ISSUED"` locks the alert, records `issued_at`/`issued_by`, and dispatches it. Returns `200` with the updated `Alert`, plus delivery failures in `meta.warnings`. Errors: `401`, `404 ALERT_NOT_FOUND`/`UNKNOWN_REGION`, `409 ALERT_ALREADY_ISSUED` (any change to an issued alert), `422`, `429`.

## 6. Analytics

### 6.1 `GET /analytics?region_id=&period=week&end_date=&months=6`

| Parameter | Default | Notes |
|---|---|---|
| `region_id` | all regions | |
| `period` | `week` | `week` = 7 days, `month` = 30, `season` = 122 (Mar–Jun, the hot season) |
| `end_date` | today (India) | Pass a future date to include forecast days |
| `months` | 6 | 1–24, the number of months in `heatwave_events` |

`data`:

- `region` (or `null`) and `period: {name, start, end, days}`.
- `temperature_trend[]`: per date, `{date, kind, tmax_c, normal_tmax_c, temp_deviation_c, heatwave_threshold_c, severe_threshold_c, above_heatwave_threshold}`. The source is `weather_snapshots`: an observation over a forecast, then the newest one. The thresholds are where the IMD rule turns that day into a heatwave or severe heatwave, for the region's zone and normal (`min(absolute, max(zone minimum, normal + departure))`). That is what the chart's colour change marks. Thresholds are `null` when no region is given (they differ per region, and the trend is then the all-region mean).
- `risk_distribution: {total_region_days, classes: [{risk_class, label, region_days, pct}]}`.
- `heatwave_events[]: {month: "YYYY-MM", heatwave_days, severe_heatwave_days, event_days}`, oldest first.
- `event_rule`: the counting rule, stated in the response itself. **One region-day counts once, with the class of the most recent prediction made for that date. An event is a region-day classed HEATWAVE or SEVERE_HEATWAVE.** This is the same daily unit as the IMD labelling rule the model learned (Part 03).
- `model_performance`: see 6.2. It is model-wide, so it does not change with `region_id` (Part 14 §3).

### 6.2 `GET /model`

The deployed model's Part 05 test-split metrics, static per model version. They come from the `model_metadata` table, written at startup from the registry's evaluation report, and are never recomputed:

```json
{ "model_version": "xgboost-20260928T100821Z-0bde51", "model_family": "xgboost",
  "explainer_id": "xgboost-20260928T100821Z-0bde51+shap.2154641e",
  "evaluation_id": "20260929T081440Z-ecce7f", "policy_version": "SEL-v1",
  "report": "ml/registry/evaluations/20260929T081440Z-ecce7f/report.md", "test_rows": 746,
  "averaging": "macro", "precision": 0.85239, "recall": 0.91447, "f1": 0.88088, "accuracy": 0.9437,
  "confidence": 0.97, "top_label_ece": 0.02789, "per_class": { "NORMAL": { "precision": 0.98803, "...": "..." } },
  "deployed_at": "2026-10-06T09:52:19Z" }
```

`confidence` is the mean top-class probability on the test split. `deployed_at` changes only when the model or explainer changes, not on a restart.

## 7. Auth

| Endpoint | Request | Response `data` | Errors |
|---|---|---|---|
| `POST /auth/login` | `{username, password}` | `{access_token, token_type: "bearer", expires_at, user: {id, username, display_name, role}}` | `401 INVALID_CREDENTIALS` (one message for every cause), `422`, `429` |
| `POST /auth/logout` | none (bearer token) | `{signed_out: true}`. The token is revoked | `401` |
| `GET /auth/me` | none (bearer token) | `{id, username, display_name, role}` | `401` (`TOKEN_EXPIRED` / `TOKEN_REVOKED` / `INVALID_TOKEN` / `UNAUTHENTICATED`) |

Accounts are created by an operator (`uv run heatwave-api create-user USERNAME --display-name "…"`). There is no self-registration. The one role is `AUTHORITY` (Part 15 §2).

## 8. Service

- `GET /api/v1/health` returns readiness: `{status: "ready", environment, model_version, model_family, explainer_id, database: "ok", notifications_mode, started_at}`, or `503 SERVICE_NOT_READY` when the database is unreachable.
- `GET /health` (un-versioned, plain JSON `{status: "ok", env}`) is liveness only.
- `GET /api/v1/reference` returns the static data the UI renders with: `regions`, `risk_classes [{code, label}]`, `alert_statuses`, `alert_channels [{code, label}]`, `delivery_statuses`, `features` (the shared label table, [`config/feature_labels.json`](../../config/feature_labels.json)) and `max_forecast_days`.

## 9. Model lifecycle and startup

- At startup the service loads, once: the production model and its explainer (`load_production_explainer`), the seasonal normals, the regions, the IMD criteria and the action mapping. It applies database migrations, syncs the `regions` table, records the deployed model in `model_metadata`, and runs one warm-up prediction.
- **Any failure stops startup**, with the reason and the command that fixes it (exit code 3 under uvicorn). Examples: no `production.json`, a missing or stale explainer, a model built with different library versions, a region without seasonal normals, the default `AUTH_SECRET_KEY` in staging or production, or `NOTIFICATIONS_MODE=live` before Part 09. `uv run heatwave-api check` runs the same startup without serving.
- **New model = restart.** Run `heatwave-registry promote` (or `rollback`), then `heatwave-explain build`, then restart the service. There is no hot swap. `MODEL_VERSION=<version>` pins an exact registered model instead of following the pointer.
- The service is stateless. Predictions, alerts, sessions (revocations) and the forecast cache all live in the database. The only exception is the rate-limit counters, which are per process, by design (ADR 0006).
- Latency (measured through the app on the dev laptop, real XGBoost and SHAP): `POST /predict` for 3 days, including 3 explanations and the database write, takes **p50 99.5 ms / p95 114.5 ms**, against Part 05's 500 ms budget, with the forecast already stored. A cache miss adds one Open-Meteo round trip (not benchmarked; bounded by the 10 s timeout × 2 attempts). Re-measure on the serving host (Part 18).
