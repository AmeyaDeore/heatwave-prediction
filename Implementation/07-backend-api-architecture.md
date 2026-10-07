# Part 07 — Backend API Architecture (FastAPI)

**Depends on:** 03 (feature computation module), 05 (production model), 06 (explainer), 08 (database schema, in parallel)
**Feeds into:** 09 (notifications), 10–14 (frontend), 15 (auth), 16 (integration)
**Owner persona:** Backend engineer

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
