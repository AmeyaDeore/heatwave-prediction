# ADR 0006 — Backend API: contract conventions, data access, live weather, lifecycle

**Status:** Accepted, 2026-10-06 (Part 07)

## Decisions

| Need | Choice | Why |
|------|--------|-----|
| Where live weather comes from (Part 07 §2) | The backend calls **Part 02's Open-Meteo forecast adapter** itself, runs Part 03's `build_features`, and stores the readings in `weather_snapshots`. A stored forecast younger than `WEATHER_CACHE_MINUTES` (60) is reused. Callers may supply `conditions` instead | One adapter and one feature path for training and serving, so features cannot drift. The frontend sends only a region. Caching in the database (not in process memory) keeps the service stateless, and leaves a record of the inputs every prediction saw. A separate ingestion job would add a scheduler and a staleness problem for no gain at 5 regions |
| What one prediction is | A **run**: the 1–3 day window for one region. Every day gets its own risk class and full SHAP explanation, and the top-level fields are the **peak day** (highest class, then higher 1 − P(NORMAL), then earlier) | Every number shown traces to a stored, explained prediction for a specific day. The banner shows the worst day in the window, which is what an authority must act on |
| Explainability in the same response (CLAUDE.md) | The Part 06 contract is returned **unchanged** under `explanation`, for the peak day and for every day in `daily[]`. The Pydantic response model mirrors it field by field | No add-on endpoint, and no reshaping that could drift. A change in the ML output fails response validation |
| Recommended actions (§3.1) | A deterministic mapping in `config/recommended_actions.yaml`: the risk class's fixed list, then factor rules on SHAP `direction` and `share_pct`. It is versioned (`actions_version`), and each action carries its `reason` | Editable wording without code changes, testable, and every action says why it is there. The factor thresholds are set so that minor factors (humidity ≈ 4 %, wind ≈ 2 % of an average explanation) only trigger an action when the model really leaned on them |
| Response envelope (§4) | `{status, data, error, meta}` on every `/api/v1` response, errors included. `meta` carries `request_id`, `api_version`, `warnings` and `idempotent_replay` | One code path for the frontend. Partial failures surface as `warnings` on a 2xx |
| Versioning | Path prefix `/api/v1`. Additive changes stay in v1, breaking changes go to v2 | Visible, simple, and cache- and proxy-friendly |
| Error taxonomy (§6) | Four categories, `client` / `auth` / `upstream` / `internal`, each with fixed status codes and stable `error.code`s. Messages carry no stack traces, SQL or paths. Upstream is 503 when unreachable and 502 when the data is bad | The UI can tell "fix your input", "sign in", "try again later" and "our bug" apart. Logs carry the detail under the same request id |
| Data access | Standard-library `sqlite3`, all SQL in one `Repository` class, numbered SQL migrations (`db/migrations/NNNN_*.sql`) with SHA-256 checks, foreign keys `ON`, WAL. The schema uses portable types (ISO text timestamps, CHECK enums) | Part 08's approach (migration scripts from day one). One file to touch for PostgreSQL. No ORM dependency for 12 tables. An edited, already-applied migration is refused |
| Auth for writes (§3.6) | Signed HS256 JWTs (stdlib HMAC) with expiry and `jti`. `scrypt` password hashes. Logout revokes the `jti` in the database. Alert writes always require a token. Reads are open unless `AUTH_REQUIRED_FOR_READS=true` | Stateless tokens (Part 15 §3). A revocation list makes logout real. No extra dependency. Part 15 owns the final per-endpoint policy, and the switch lets it decide without code changes |
| Rate limiting | An in-process fixed window per client address, on `predict`, `alert_writes` and `login`, configurable. `429` with `Retry-After` | Stops runaway poll loops and password guessing. Shared counters (Redis) are not worth adding for one instance |
| Idempotency (§4) | A client-generated `client_request_id` (UUID) is unique per alert. The same id and body replays (200), and the same id with a different body is a 409 | Guards against double submission without making identical alerts impossible. Every new alert needs a new id |
| Draft vs issued (§3.4) | One record, an explicit `status` (`DRAFT ⇄ READY → ISSUED`), changed through `PATCH`. ISSUED is final. Only reaching ISSUED dispatches | As specified: no separate endpoints, and saving a draft can never notify anyone |
| Partial delivery failure (§6) | Per-channel status rows (`READY → PENDING → NOTIFIED/FAILED`), each committed after its own attempt. A channel exception is caught and recorded as FAILED, and failures are listed in `meta.warnings` | A failed channel is visible on the record and in the response, and never blocks the other channels |
| Dispatch timing | Synchronous within the request, through a `Notifier` interface. The mock notifier logs, and can be told to fail chosen channels | The mock is instant, so the issue response shows real statuses. Part 09 owns providers, retries and any move to a background task, behind the same interface |
| Model lifecycle (§5) | Load the model and explainer once at startup through the registry, warm up with one prediction, and **refuse to start** on any problem. A new model means promote, rebuild the explainer, restart | Fails at deploy time rather than on a user's first request. Hot-swapping adds failure modes that this scale does not need |
| Concurrency | Sync route handlers (FastAPI's thread pool) and one SQLite connection per request. Model and SHAP calls go through a lock | SQLite and SHAP calls are blocking. SHAP/XGBoost thread-safety is not documented, and a ~30 ms critical section is negligible at this load |

## Alternatives rejected

- **Frontend sends raw features:** this puts unit conversion and seasonal normals in the browser, the exact training/serving drift Part 03 was built to prevent. Supplying conditions is still supported, but it goes through the same server-side feature path.
- **Separate `/explain` endpoint:** explicitly ruled out by CLAUDE.md (explanations are a core contract).
- **SQLAlchemy/Alembic:** heavier than this schema needs, and plain numbered SQL files satisfy Part 08 §6. Revisit at the PostgreSQL migration.
- **Two endpoints for draft and issue:** ruled out by Part 07 §3.4.
- **Background dispatch now:** with only a mock notifier, it would add polling complexity with nothing to wait for. Part 09 decides.
- **A process-wide forecast cache:** state that is lost on restart, and different per worker.

## Consequences

- `heatwave-ml` is now a backend dependency (workspace source). The backend imports features, the registry, the explainer and the Open-Meteo adapter, and reimplements none of them.
- Part 07 needed tables before Part 08 existed, so migration `0001_initial` implements Part 08 §2–4 (regions, weather_snapshots, prediction_runs + predictions + prediction_factors, users, revoked_tokens, alerts, alert_channel_deliveries, model_metadata). Part 08 reviews it, does the field-by-field mockup cross-check, and adds changes as new migrations.
- Analytics are empty until data accumulates. There is no historical backfill of `weather_snapshots`/`predictions` yet (Part 08/16).
- Rate-limit counters are per process: with N workers, the effective limit is N times the setting.
