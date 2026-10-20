# Part 07 — Backend API Architecture (FastAPI)

**Depends on:** 03 (feature computation module), 05 (production model), 06 (explainer), 08 (database schema, in parallel)
**Feeds into:** 09 (notifications), 10–14 (frontend), 15 (auth), 16 (integration)
**Owner persona:** Backend engineer

> **Revision 2 (2026-10-20, examiner feedback):** the backend splits in two. **§A:** the FastAPI service built in this part becomes the internal **ML inference service** (prediction, SHAP, live features, model lifecycle, all kept as built). **§B:** a new **Node.js + Express application API** on MongoDB takes over the application responsibilities in §2 (persistence, read endpoints, alerts, notifications, auth) and serves the **same `/api/v1` contract**, extended additively. Sections 1–9 below remain the specification both halves follow. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

## 1. Objective

Design the REST API service that sits at the center of the architecture diagram — the single point through which the frontend, the ML pipeline's outputs, the database, and the notification service all connect.

## 2. Service responsibilities (and explicit non-responsibilities)

The backend **is responsible for**:
- Accepting weather/feature input and returning a prediction + explanation.
- Persisting predictions, alerts, and related records to the database.
- Serving read endpoints for the dashboard, analytics, and alert history.
- Triggering the notification service when an alert is issued.
- Enforcing authentication/authorization on protected actions (Part 15).

The backend **is not responsible for**: training or retraining models (that's Part 04/05, run offline, producing an artifact this service only loads); performing SHAP background-data computation from scratch (Part 06 hands it a ready-to-use explainer); talking directly to IMD/NASA POWER for historical training data (Part 02 owns that; the backend only needs current/forecast conditions for live inference, and can either call the same source adapters or receive already-ingested current conditions from the pipeline — decide and document which).

## 3. Endpoint inventory

Design each endpoint below with a full request/response contract (field names, types, required/optional, and error cases) before implementation begins.

### 3.1 `POST /api/predict`
- **Purpose:** given current/forecast weather conditions for a location, return the heatwave risk prediction and its explanation.
- **Input:** location identifier (or raw feature values, if the caller supplies them directly — decide which; the UI mockup implies the backend may fetch current conditions for a named location itself, reducing what the frontend needs to send).
- **Output:** risk class (`NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`), probability/confidence score, the raw input feature values used (temperature, humidity, wind speed, temperature deviation, etc., as shown in the UI), the ranked SHAP top-factors list with signed contributions (Part 06's contract), the forecast window this prediction covers (next 1–3 days), and a recommended-actions list (the UI shows templated authority actions like "Issue ward-level heat advisory," "Activate cooling centres" — define this as a deterministic mapping from risk class + top factors to a fixed action list, not free text).
- **Error cases to define:** unknown location, missing/invalid input data, upstream weather-source failure, model/explainer not loaded.

### 3.2 `GET /api/weather`
- **Purpose:** return current weather data for a location (or all monitored locations).
- **Output:** location, current temperature, humidity, wind speed, and whatever else the dashboard's "Current Temperature" and regional table need.

### 3.3 `GET /api/alerts`
- **Purpose:** list heatwave alerts (for the Alert Management screen, Part 13).
- **Output:** per alert — alert ID, status (e.g., draft/ready/issued), severity, target region, created date, and distribution-channel status per channel (public mobile alert, government portal, public display boards, emergency services, hospitals/health centres — matching the UI mockup's distribution list).

### 3.4 `POST /api/alerts`
- **Purpose:** create/issue a new alert (protected action — requires authentication, Part 15).
- **Input:** target region, severity, public advisory message text, which distribution channels to notify.
- **Behavior:** persists the alert (Part 08), triggers the notification service (Part 09) for the selected channels, and records delivery status per channel.
- **Support for the UI's two-step flow:** "Save as Draft" vs. "Issue Warning" — model this as an explicit alert status field, not two different endpoints, so the same alert record transitions cleanly from draft to issued.

### 3.5 `GET /api/analytics`
- **Purpose:** power the Analytics — Trends & Insights screen (Part 14): temperature trend over a period, heatwave event counts per month, risk distribution breakdown, and the model performance metrics (Precision/Recall/F1/Confidence) surfaced from Part 05's evaluation report.
- **Design decision:** model performance figures are static per deployed model version (they don't change per request) — serve them either from a small config/metadata store populated at deployment time from Part 05's report, or a dedicated lightweight endpoint, rather than recomputing them live.

### 3.6 Auth-related endpoints
- Covered fully in Part 15, but note here that this service must expose login/session endpoints and must gate `POST /api/alerts` (and any other write action) behind them.

## 4. Cross-cutting API design decisions

- **Response envelope consistency** — pick one consistent JSON response shape (e.g., always including a status/error field) across all endpoints so the frontend can handle errors uniformly.
- **Versioning** — prefix routes so the API can evolve without breaking the frontend (e.g., a version segment in the path).
- **Validation** — every input is validated against a defined schema before touching the model or database; invalid input returns a clear 4xx error, never a silent default.
- **CORS** — explicitly configure allowed origins for the frontend's dev and production URLs (from Part 01's environment config).
- **Rate limiting** — at minimum on `POST /api/predict` and `POST /api/alerts`, to prevent accidental hammering from a misbehaving frontend poll loop.
- **Idempotency** — decide whether repeated identical `POST /api/alerts` calls should create duplicate alerts or be treated as idempotent (recommend requiring an explicit new alert each time, but guard against accidental double-submission from the UI with a client-generated request identifier).

## 5. Loading and lifecycle of the ML artifacts

- The model artifact (Part 05) and explainer artifact (Part 06) are loaded once at service startup, not per-request, for performance.
- Define a startup health check that fails fast if the artifacts can't be loaded, rather than starting the service in a broken state that only fails on the first real prediction request.
- Define how a model update (a new production version from Part 05) gets picked up — a service restart pointed at the new artifact version is sufficient for this project's scale; document this as the process rather than building live hot-swapping, which is unnecessary complexity here.

## 6. Error handling strategy

- Distinguish, in both logs and API responses, between: client errors (bad input), upstream failures (weather data source down), and internal failures (model/explainer error). Each should map to an appropriate HTTP status and a clear, non-leaky error message (no stack traces returned to the client).
- Every failure on a write path (e.g., alert creation succeeds in the database but notification dispatch fails) must not be silently swallowed — define how partial failures are surfaced (e.g., the alert record shows per-channel delivery status, so a failed SMS doesn't hide behind a "success" response for the whole request).

## 7. Non-functional requirements

- `POST /api/predict` end-to-end latency (including SHAP explanation) should be low enough for a responsive dashboard interaction — treat Part 06's benchmarked explanation latency as a budget input here.
- The service must be stateless with respect to application logic (all state lives in the database, Part 08), so it can be restarted or scaled horizontally without losing in-flight data.
- Logging must include enough structured detail (endpoint, status, latency, and for predictions, the resulting risk class) to support the analytics and debugging needs of Part 14 and Part 18.

## 8. Acceptance criteria / "done"

- [x] Full request/response contract documented for every endpoint in Section 3. *(`docs/api/README.md` §2 (fields, types, required/optional, error cases per endpoint) plus the generated `/openapi.json`. Routes are under `/api/v1`.)*
- [x] Response envelope, versioning, validation, CORS, and rate-limiting conventions decided and documented. *(`{status, data|error, meta.request_id}`; `/api/v1`; strict Pydantic bodies with 422 that never echoes input; origin allow-list; 30/20/10 per minute on predict / alert writes / login; idempotency via `client_request_id`. `docs/api/README.md` §1, ADR 0006. The weather-source decision, the plan's open question, is §4: read what the pipeline ingested.)*
- [x] Model/explainer startup-loading and health-check behavior implemented. *(Loaded once in `lifespan`; a missing, stale or tampered artifact stops the process. `/health` is liveness, `/api/v1/health/ready` reports model, explainer and weather freshness with a 503 when not ready. A model update is promote, rebuild explainer, restart: §5.)*
- [x] Error-handling taxonomy implemented consistently across endpoints. *(client / upstream / internal with fixed statuses and codes; unexpected errors become a 500 with no trace or paths, and the log carries the traceback under the same request id. Tested on every endpoint family.)*
- [x] Draft-vs-issued alert status flow implemented as specified. *(One record, one `status`: DRAFT → READY → ISSUED, ISSUED immutable. Per-channel delivery status with FAILED and a reason, so a partial failure is visible. Idempotent create.)*
- [x] Each endpoint independently testable against a mocked database and mocked model/explainer. *(`create_app(settings, predictor=, weather=, repo=, notifier=)`; 75 tests use fakes with no model, file or database, plus 6 on the real production model.)*

## 9. Handoff note template

> API base URL: <value>. Endpoint contracts documented at: <path/link>. Auth requirement per endpoint: <summary>. Part 08 owner confirms schema matches these contracts; Part 10 (frontend) can now build against this documented contract even before every endpoint is fully implemented, using mocked responses.

**Also produced:** `POST/PATCH /alerts` behind a bearer token (a minimal login; Part 15 extends it), `GET /weather`, `/analytics` (model performance from the promotion pointer), `/predictions/latest`, `/regions`, `/alert-channels`, structured JSON logs, ADR 0006 and log 07. **Not done, by design:** persistence is an in-memory `Repository` until Part 08 (so the service must not be deployed yet), notifications are a `MockNotifier` until Part 09, and users are one seeded demo account until Part 15. Analytics trend and counts come from stored predictions until Part 08/14.

**Filled-in handoff:** see §9 of [`docs/api/README.md`](../docs/api/README.md).

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **In progress.** ✅ §A built (step 2). ✅ §B places, weather and predictions (step 4) and ✅ login + **the frontend switch to the Node API** (step 5), all uncommitted. ⏳ §B alerts (step 8), analytics and the generated `openapi.json` (step 9). The FastAPI `app` role is no longer what the frontend calls; it stays runnable as the reference until step 11 retires it. **Also fixed in step 4:** FastAPI `GET /weather` without `region_id` ignored `lead_days` (it always returned today); it now honours it, and lead 0 is unchanged.

**Why:** the examiner requires MongoDB (M2), login (M1) and an alert system on Node.js + MongoDB (M5), and the application stack is MERN. The live prediction path must still use the Python feature module, model and explainer (Part 03 §6, Part 16 §3.1), so prediction stays in Python. Everything else that §2 assigns to "the backend" moves to Node.js. The contract does not change shape, so the Part 10 frontend and its contract tests carry over.

### §A — ML inference service (FastAPI, `backend/`, internal)

Keeps, unchanged: model and explainer loading at startup with fail-fast (§5), live features from `heatwave_ml.features`, the weather-source decision (it reads the pipeline's ingested forecast file), the recommended-action mapping (`config/recommended_actions.yaml`), the prediction + explanation contract, JSON logging and the error taxonomy.

| Internal endpoint | Status | Used by |
|---|---|---|
| `POST /api/v1/predict` | existing | Node `POST /predict` |
| `POST /api/v1/predict/batch` | **new, additive** (list of `{region_id, lead_days}` → list of predictions; one SHAP batch call, ~0.34 s for 15 rows per Part 06) | Node batch scoring (Part 11 R2) |
| `GET /api/v1/weather` | existing | Node `GET /weather`, weather snapshots |
| `GET /api/v1/regions` | existing | Node startup consistency check |
| `GET /api/v1/model` | **new, additive** (the `model_performance` payload already built for `/analytics`, plus per-zone figures after Part 05 R2) | Node `model_metadata` (Part 08 R2) |
| `GET /health`, `GET /api/v1/health/ready` | existing | Node readiness, Part 18 |

- **Service role:** a `SERVICE_ROLE` setting. `app` is today's full service, kept working (and its tests passing) until Node replaces it in Part 16 R2. `ml` mounts only the endpoints above, uses no database, and keeps no prediction history (Node persists).
- **Access:** in role `ml`, the service is bound to the internal network, CORS is off, and every request outside local/test must carry `X-Service-Token` = `ML_SERVICE_TOKEN`.
- **Not removed:** the SQLite repository, alerts, notifications and auth code stay in the repository as the reference implementation that §B ports and its tests describe. They are retired from the request path, not deleted.
- **Freeze during the transition:** while both exist, the FastAPI `app` role gets fixes only, no new features. Every behaviour change lands in Node, so the two implementations cannot drift while the frontend still points at FastAPI.

### §B — Application API (Node.js + Express, `server/`, public)

**Responsibilities:** everything in §2 except computing predictions. It persists predictions, weather snapshots, alerts, deliveries and users in MongoDB (Part 08 R2), serves the dashboard, analytics and map reads, runs notifications (Part 09 R2), enforces auth (Part 15 R2), and calls §A for every prediction.

**Contract rules (unchanged from §4 and `docs/api/README.md`):** the `/api/v1` prefix; the `{status, data | error, meta.request_id}` envelope; `X-Request-ID`; the client / upstream / internal taxonomy with the same codes; strict validation (an unknown field is a 422 that never echoes input); the CORS allow-list; rate limits (predict 30, alert writes 20, login 10 per minute per IP); idempotent alert create via `client_request_id`; exact risk vocabulary. **New error code:** `ML_SERVICE_UNAVAILABLE` (`upstream`, 503) when §A is unreachable or not ready. Prediction requests fail clearly. Reads of stored data keep working.

**Endpoint inventory (R2):**

| Endpoint | Source | Auth (Part 15 R2) | R2 change |
|---|---|---|---|
| `POST /auth/login`, `GET /auth/me` | MongoDB `users` | open (rate limited) / token | moved to Node |
| `POST /auth/logout` | MongoDB `revoked_tokens` | token | **new** (Part 15 §4) |
| `GET /regions` | MongoDB `places` (seeded from `config/regions.yaml`) | token | adds `division`, `kind`, `parent` |
| `GET /weather` | §A, stored as a weather snapshot | token | moved |
| `POST /predict` | §A → stored in `predictions` → auto-draft rule (Part 09 R2) | token | moved, response unchanged |
| `POST /predictions/batch` | §A batch → stored | token | **new**: `{region_ids?, lead_days?, only_missing?}`. Used by the dashboard "score places without a prediction" button and the seeding CLI (Part 11 R2) |
| `GET /predictions/latest` | MongoDB | token | unchanged (one place) |
| `GET /predictions/latest-by-region` | MongoDB, one aggregation | token | **new**: `?lead_days=&division=` → `{items: PredictionOut[], missing_region_ids}`. The composite call Part 11 §4 asks for (map, table, metric cards) |
| `GET /predictions/{id}` | MongoDB | token | moved |
| `GET /alerts`, `GET /alerts/{id}`, `POST /alerts`, `PATCH /alerts/{id}`, `GET /alerts/{id}/attempts` | MongoDB `alerts`, `notification_attempts` | token | moved; `AlertOut` adds `origin` (`manual` / `auto_draft`) |
| `GET /alert-channels` | `config/alert_channels.yaml` | token | moved |
| `GET /advisories` | MongoDB `public_advisories` | **open** (public feed) | moved |
| `GET /analytics` | MongoDB aggregations + `model_metadata` | token | adds `division`, `lead_days` filters and `place_comparison[]` (Part 14 R2) |
| `GET /health`, `GET /health/ready` | process / MongoDB + §A readiness | open | readiness adds `database` and `ml_service` |

- **CLIs** (Part 11 R2 decision: "both" button and CLI): `score-all` scores every place × lead 0–3 through the batch logic; the 6-hourly refresh runs it (Part 02 R2.3b). `import-history` loads the **Python-labelled** observed-history export (Part 03 R2.3) into `weather_snapshots` and rebuilds `history_summaries` (Part 14 R2.6). It is idempotent through the unique index and never relabels anything.
- **OpenAPI:** `docs/api/openapi.json` becomes generated from the Node API's request/response schemas, so it cannot drift. The frontend's `contract.test.ts` keeps checking against it, and a server test validates live responses against it. **Conflict to manage:** today that file is generated *from FastAPI*. At the switch, FastAPI's internal contract moves to `docs/api/ml-service-openapi.json`, and the Node API's generator takes over `openapi.json`. The two must never write the same file.
- **Logging:** one JSON line per request with the same fields as today (`request_id`, `method`, `path`, `status`, `latency_ms`, `user_id`, plus `risk_class`/`region_id`/`lead_days` and `alert_id`/`alert_status`). Never tokens or passwords.
- **Statelessness:** all state in MongoDB, so the API can restart freely. The notification queue's durable state is in MongoDB too (Part 09 R2).

### Transition (no big-bang switch)
1. §A role `ml` and the two additive endpoints, with the existing tests green.
2. §B built against the contract and tested with an in-memory MongoDB and a fake ML service.
3. Part 16 R2: point `VITE_API_BASE_URL` at Node, run the frontend contract and E2E tests, then retire role `app` from deployment.

### R2 acceptance criteria
- [x] §A: `SERVICE_ROLE=ml` implemented; `POST /predict/batch` and `GET /model` added and tested; service token enforced outside local/test; all existing backend tests still pass. *(2026-10-20: 42 tests in `backend/tests/test_ml_service_role.py`. On the real XGBoost model and explainer, the batch for all 5 regions × 4 leads equals 20 single `/predict` calls field for field, in 159 ms vs 291 ms. The existing suite is unchanged: 281 → 331 passed with the new tests, and the same 6 pre-existing `test_production_model.py` errors (master plan §4.0). `openapi.json` regenerated: purely additive. The real-token rule is enforced at startup outside local/test (the placeholder or under 32 characters is refused). In local/test the token is checked whenever a real value is set.)*
- [ ] §B: every endpoint in the R2 inventory implemented on MongoDB with the same envelope, taxonomy, validation, CORS, rate limits and idempotency rules. *(**Partly, step 4 (2026-10-20):** `/regions`, `/weather`, `/predict`, `/predictions/batch`, `/predictions/latest`, `/predictions/latest-by-region`, `/predictions/{id}` and readiness, with the envelope, taxonomy, strict 422 validation that never echoes input, a 400 for malformed JSON, and the predict rate limit with Retry-After. **Not yet:** auth and CORS (step 5), alerts with idempotency (step 8), analytics (step 9). These routes are open until step 5, as the FastAPI reads are today.)*
- [x] `ML_SERVICE_UNAVAILABLE` behaviour tested: predictions fail clearly, stored reads still work. *(Tests: client unreachable, timeout, 5xx, rejected token, non-JSON → 503 `ML_SERVICE_UNAVAILABLE`; client/upstream errors (404, 422, 503 weather) pass through unchanged. **Live, 2026-10-20:** with the ML service stopped, `POST /predict` → 503, `latest` and `latest-by-region` → 200, readiness → 503 `ml_service: unavailable`. MongoDB down → 503 `DATABASE_UNAVAILABLE`, not a 500.)*
- [x] `GET /predictions/latest-by-region` returns the whole map/table snapshot in one call (one MongoDB aggregation on the Part 08 R2 index). *(Items in catalog order + `missing_region_ids`, optional `division`; the query plan uses `latest_per_place` (a DISTINCT_SCAN), asserted in `server/src/db/migrations.test.ts`.)*
- [ ] `docs/api/openapi.json` generated from the Node schemas; `docs/api/README.md` updated with the R2 additions; the frontend contract test passes against it. *(**Deviation, decided in step 5:** generation from the Node schemas is moved to **step 9**, when Node serves the whole inventory. Generating it now would drop the alert and analytics contracts the frontend's types and contract test still rely on. Until then `openapi.json` stays FastAPI-generated (the full target contract, purely additive since R2), and `server/src/auth.test.ts` checks Node's `TokenOut`/`UserOut` against it. `docs/api/README.md` documents the Node additions.)*
- [x] Node never computes features, predictions, SHAP or recommended actions: it stores and serves §A's output (checked in review and by a test that a stored and re-read prediction equals, field for field, what §A returned). *(The ML payload is stored unchanged in `predictions.data`. Test `stores the ML service's prediction and serves it back field for field`. **Live on the real model:** the `/predict` response, `latest`, `by id` and the raw MongoDB `data` were all identical (12 fields, 7 SHAP factors).)*
