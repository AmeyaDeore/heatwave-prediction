# Part 18 — Deployment, DevOps & Monitoring

**Depends on:** 17 (tests gate what gets deployed), 01 (environment/config conventions)
**Feeds into:** nothing further — this is the final part of the sequence, and feeds back into ongoing operation of the live system
**Owner persona:** Backend engineer / whoever owns infrastructure

> **Revision 2 (2026-10-20, examiner feedback):** three deployable services (React static build, Node.js API, internal FastAPI ML service) plus MongoDB per environment, replacing the single FastAPI + SQLite file. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

## 1. Objective

Define how the system (ML artifacts, backend, database, frontend, notification integrations) moves from a working local/integration setup to a reliably running deployed environment, and how it is observed and maintained once live.

## 2. Environments

Define at least three distinct environments, each with its own configuration set (per Part 01's environment-variable strategy):
- **Local** — individual developer machines, mock providers, local SQLite file, as established in Part 01.
- **Staging/Integration** — the shared environment used in Part 16, ideally with sandboxed (not production) notification-provider credentials, used for pre-release verification.
- **Production** — the real deployed system, with real provider credentials, serving real authority users.

Each environment's configuration values (database path, API keys, allowed CORS origins, model artifact version) must be fully isolated from the others — a bug in staging must never be able to send a real SMS through production credentials, for example.

## 3. Deployment architecture

- **Backend + ML artifacts:** deploy the FastAPI service as a single deployable unit that bundles or loads the production model and explainer artifacts (Part 05/06) at startup, per the loading/health-check behavior defined in Part 07 Section 5. Decide the hosting approach (a single small server/container is proportionate to this mini-project's scale) and document it, rather than over-engineering for scale the project doesn't need.
- **Database:** the SQLite file needs a defined, persistent storage location that survives redeploys/restarts of the backend service — treat this as a critical requirement, since losing the SQLite file means losing all historical predictions and alerts (the entire basis of the Analytics page).
- **Frontend:** deploy the built frontend as static assets served independently of the backend (or served by it, if simpler for this project's scale) — document which, and confirm the deployed frontend's API base URL configuration correctly points at the deployed backend for each environment.
- **Notification providers:** confirm production credentials are configured only in the production environment, distinct from the staging/local mock modes established in Part 09.

## 4. CI/CD pipeline

- **On every change:** run the fast tier of the automated test suite (Part 17) and the linting/formatting checks (Part 01) as a required pre-merge gate.
- **On merge to main:** run the full test suite (including the slower model-quality regression tests from Part 17 Section 2.4), then build deployable artifacts for backend and frontend.
- **Deployment trigger:** define whether deployment to staging is automatic on every merge (recommended, since it keeps staging always representative of the latest code) while deployment to production is a deliberate, manually-triggered promotion step (recommended for a system whose alerts have real-world consequences).
- **Model artifact promotion:** define this as a distinct process from code deployment — a new production model (Part 05 Section 5's pointer update) should be its own deliberate, tracked promotion event, not something that happens implicitly as a side effect of an unrelated code change.

## 5. Rollback strategy

- Backend/frontend code: ability to redeploy the previous known-good build quickly if a release introduces a regression.
- Model artifact: since Part 05 retains archived (non-production) candidate and prior-version artifacts, define the process for pointing production back at a previous model version if a newly promoted model is found to perform poorly in practice.
- Database: since schema migrations (Part 08 Section 6) are applied incrementally, ensure each migration has a considered rollback/reversibility plan, or at minimum a backup taken immediately before applying any migration to production.

## 6. Monitoring & observability

- **Application health:** basic uptime/health-check monitoring on the backend service (reusing the startup health check from Part 07 Section 5 as a liveness signal).
- **Operational metrics to track in production:** prediction request volume and latency, error rates by category (per Part 07 Section 6's error taxonomy), notification dispatch success/failure rates per channel (surfacing Part 09's audit log data), and login failure rates (a signal for both usability issues and potential brute-force attempts, tying back to Part 15 Section 7).
- **Model-behavior monitoring:** track the live distribution of predicted risk classes over time in production and compare it periodically against the training-data distribution documented in Part 03 Section 2 — a significant, sustained drift is an early signal that the model may need retraining against fresher data (a natural future extension of the Part 02 ingestion pipeline).
- **Alerting on the monitors themselves:** define who is notified, and how, if the backend goes down, if notification dispatch failure rates spike, or if the health check fails — for a public-safety-adjacent system, silent operational failure is a serious risk to plan against explicitly.

## 7. Data and secret handling in production

- Confirm production credentials (weather-source API keys, notification provider keys, any auth signing secrets) are stored using a proper secrets-management approach for the chosen hosting environment, never committed to the repository, consistent with Part 01's foundational rule.
- Define a backup cadence for the production SQLite file (per Part 08 Section 5) and confirm backups are actually tested by restoring them at least once, not just taken and assumed to work.

## 8. Non-functional requirements

- A fresh production deployment from a clean state (empty database, freshly loaded model artifact) should be achievable by following this part's documentation alone, without tribal knowledge.
- Any single component failure (notification provider down, weather-source API down) should degrade the system gracefully (per the error-handling and loading-state conventions established throughout Parts 07 and 10) rather than taking the whole system down.

## 9. Acceptance criteria / "done"

- [ ] Three environments defined with fully isolated configuration.
- [ ] Deployment architecture documented for backend+ML artifacts, database, frontend, and notification credentials.
- [ ] CI/CD pipeline implemented per Section 4, including the distinct model-artifact-promotion process.
- [ ] Rollback strategy documented and tested at least once (a deliberate rollback drill) for both code and model artifact.
- [ ] Health checks, operational metrics, and model-drift monitoring implemented.
- [ ] Alerting-on-failure defined with a named responsible recipient.
- [ ] Secrets management confirmed in place; backup-and-restore tested at least once.

## 10. Handoff note template

> Production deployment location: <details>. CI/CD pipeline at: <path/link>. Monitoring dashboard/alerts at: <link>. Rollback drill last performed: <date, outcome>. This concludes the initial implementation plan sequence — ongoing operation should reference Sections 5–7 of this file.

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** ⏳ **Not started** (step 11).

### R2.1 Deployment architecture
| Component | Deployment | Notes |
|---|---|---|
| Frontend | static build served by the Node API (simplest at this scale) or any static host | `VITE_API_BASE_URL` per environment |
| Node.js API (`server/`) | one container / process | the only public backend; HTTPS terminated in front of it |
| ML service (`backend/`, `SERVICE_ROLE=ml`) | one container on the internal network only | loads the production model + explainer at startup (§3, unchanged); the bundle is shipped as a release artifact built on the designated training platform (Part 04 R2) |
| MongoDB | managed (for example Atlas free/shared tier) or self-hosted with auth + TLS | **one database per environment**; local uses the Part 01 R2 setup |

A compose file for local and staging runs all four together. Production may use the same file on a single small host, which is proportionate to scale.

### R2.2 Environments and secrets
New secrets per environment: `MONGODB_URI`, `JWT_SECRET`, `ML_SERVICE_TOKEN` and the provider keys (now read by the Node API). They are isolated per environment (§2). Staging uses sandbox providers, never production credentials.

### R2.3 CI/CD
Pre-merge adds server lint, typecheck and tests, and the frontend build. Merge to main adds the E2E suite against the composed stack. Model promotion stays a separate, deliberate event (§4), and the ML service image references the promoted bundle by SHA-256.

### R2.4 Backups, rollback, monitoring
- MongoDB: scheduled `mongodump` with retention, plus a **tested restore** (§7), replacing the SQLite file copy. Migrations: back up before applying (§5).
- Rollback: previous Node API and ML service images; the model rollback procedure is unchanged.
- Monitoring adds MongoDB availability, ML service readiness as seen from the Node API, login failures and lockouts (Part 15 R2), suggestion and issue counts, and delivery failure rates per channel from `notification_attempts`.

### R2 acceptance criteria
- [ ] Compose definition for the four components; a clean-checkout deployment works from this document alone.
- [ ] ML service unreachable from outside; Node API is the only public backend.
- [ ] Per-environment MongoDB with auth and TLS outside local; backup and restore tested once.
- [ ] CI runs Python, server, frontend and E2E suites as specified.
- [ ] Monitoring additions in R2.4 in place with a named alert recipient.
