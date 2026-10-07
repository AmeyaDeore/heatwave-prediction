# ADR 0006 — Backend API: conventions, weather source, seams

**Status:** Accepted, 2026-09-29 (Part 07)

## Decisions

| Need | Choice | Why |
|------|--------|-----|
| Live weather for inference (Part 07 §2 asks to decide) | Read the conditions the pipeline already ingested (`WEATHER_FEATURES_FILE`); the backend never calls a weather provider | One fetch and unit-normalisation path (Parts 02/03), a fast API that tests offline, no provider credentials in the backend, and an outage becomes *stale, flagged* data rather than failed requests. Cost: someone must schedule the ingestion (Part 16/18), and until then the sample ages. |
| What `POST /predict` takes (§3.1) | `region_id` + `lead_days` (0–3). No raw feature values | The UI names a place, not measurements. Accepting caller-supplied features would need its own validation and would let a client bypass the shared feature path. It can be added later without breaking the contract. |
| Route prefix and versioning (§4) | `/api/v1/...` | A version segment lets the contract evolve behind `/v2`. The plan's `/api/predict` etc. are the same routes with the segment inserted. |
| Envelope (§4) | `{status, data, meta:{request_id}}` / `{status:"error", error:{kind, code, message, details}, meta}` | One shape for everything. `kind` (client / upstream / internal) is in the body as well as the log, so the UI can say "try again later" vs "fix your input". |
| Validation (§4) | Pydantic, `extra="forbid"` on request bodies, 422 listing field + message only | A typo is an error, never a silent default. Submitted values are never echoed back (they could be attacker-chosen text). |
| Explanation (core contract) | Part 06's `Explanation.to_dict()` returned unchanged inside the prediction | The contract is defined once, in Part 06, and tested there. The API adds fields around it, never inside. |
| Recommended actions (§3.1) | `config/recommended_actions.yaml`: class → list, plus factor-triggered extras; a pure function | Deterministic and auditable, and the authority can edit the wording without a code change. Free text was ruled out by the plan. |
| Alert lifecycle (§3.4) | One `status` field: DRAFT → READY → ISSUED on one record, via `POST` (initial status) and `PATCH` (transitions and edits). ISSUED is immutable | Matches the UI's two-step flow with one record and no second endpoint. A wrong warning is corrected by a new alert, so the issued history stays trustworthy. |
| Issue and partial failure (§6) | Save ISSUED with every channel PENDING, dispatch each, record each result. A failed channel is FAILED + reason; the alert stays ISSUED and the response is 201 with `delivery_summary` | A crash mid-dispatch leaves a truthful record. One dead channel never hides behind a whole-request "success" or blocks the others. |
| Idempotency (§4) | Client-generated `client_request_id` (UUID), per user. Replay with identical content → 200 + the original alert. Same id, different content → 409. New id → always a new alert | Guards double-submit from the UI without merging genuinely separate warnings. |
| Rate limiting (§4) | In-process sliding window per client IP: predict 30/min, alert writes 20/min, login 10/min | Stops a runaway poll loop and slows password guessing. A shared store is unnecessary for one node. |
| Auth now (§3.6) | scrypt password hashes, HMAC-signed expiring bearer tokens, a `UserStore` seam, one seeded demo user only in `local`/`test` | Part 07 must gate writes now, but users live in Part 08's table and Part 15 owns the design. Built on the standard library, so Part 15 replaces the store rather than the mechanism. |
| Persistence (Part 08 in parallel) | `Repository` Protocol + an in-memory implementation | Keeps every endpoint testable against a mocked database (§8) and lets Part 08 land without touching the routers. **The in-memory store loses data on restart and must not be deployed.** |
| Notifications (Part 09) | `Notifier` Protocol + `MockNotifier` (logs only) | The same seam argument. `NOTIFICATIONS_MODE` will select the real one. *(Superseded by [ADR 0008](0008-notification-service.md): `NotificationService` replaced `MockNotifier`.)* |
| Startup and updates (§5) | Load model + explainer in `lifespan`; any failure stops the process. A new model = promote, rebuild explainer, restart. No hot-swap | A broken service never looks healthy, and Part 06's stale-explainer refusal becomes a startup failure. |
| Concurrency | SHAP calls serialised by a lock; endpoints are sync functions run in the thread pool | SHAP's C extension is not documented as thread-safe. About 35 ms per request makes one process plenty. |
| Analytics numbers (§3.5) | Model performance from the promotion pointer; trend, events and distribution from stored predictions | The performance figures are static per model version. Real history arrives with Parts 08/14. |

## Alternatives rejected

- **Backend calls Open-Meteo directly:** duplicates the fetch and unit logic, and turns a provider outage into request failures.
- **Two endpoints (`/alerts/draft`, `/alerts/issue`):** two ways to make one record, and the transition between them becomes ad hoc.
- **Hiding a channel failure behind a 5xx or a bare 200:** a 5xx suggests the alert was not created, and a bare 200 hides that a hospital was not notified.
- **Idempotency by content hash:** two real warnings for the same region and text are legitimate.
- **JWT library / passlib:** more dependencies for what the standard library does in about 60 lines, in a part that Part 15 will replace anyway.
- **Pinned `MODEL_VERSION`:** the explainer and the pointer must agree, so a second way to choose a model invites a mismatch. Promote instead.

## Consequences

- Part 08 must implement `Repository` and add a unique key on `(created_by, client_request_id)`. *(Done 2026-10-07, ADR 0007.)*
- Part 09 implements `Notifier.send` and must return FAILED with a reason rather than raise.
- Part 15 replaces `UserStore` and extends `current_user` with roles and region scoping.
- Part 18 needs proxy-aware client IPs, a schedule for the ingestion, and a real `AUTH_SECRET_KEY`.
