# AI Heatwave Prediction & Early Warning System — Master Implementation Plan

## Purpose of this document set

This is not a single build prompt. It is a **sequenced set of standalone implementation plans**, one per `.md` file, each scoped tightly enough to be executed on its own (by a human developer or an AI coding agent) without needing every other file open at once. Each file states its own inputs, outputs, and "done" criteria so it can be picked up independently, in order.

Read this file first. It explains the system as a whole, the build order, and how the parts hand off to each other. No code appears anywhere in this set — only specifications, contracts, decisions, and step-by-step task breakdowns. Writing the actual code from each plan is a separate, later activity.

> **Revision 2 — examiner feedback (2026-10-20).** The examiner made five features mandatory. They are folded into the existing parts below. They are not a separate plan.
>
> | ID | Mandatory feature | Main part(s) | Also touches |
> |---|---|---|---|
> | **M1** | User login | 15 (Node.js + MongoDB auth) | 10 (login page, route guard), 07, 16, 17 |
> | **M2** | MongoDB integration | 08 (MongoDB design) | 01, 07, 09, 14, 15, 18 |
> | **M3** | Data analysis for places in Maharashtra (place selection; filters are our proposal) | 14 (analytics) | 02/03 (places, normals, data), 07, 08, 11 |
> | **M4** | Interactive Maharashtra map with predictions and risk levels | 11 (dashboard map panel) | 10 (map component), 02 (place list), 07 (batch endpoint), 14 |
> | **M5** | Alert system on Node.js + MongoDB, connected to the prediction workflow | 09 (Node notification service) + 13 (alerts page) | 07, 08, 16 |
>
> The application stack becomes **MERN**: MongoDB, Express on Node.js, and React (the Part 10 frontend, unchanged in stack). The completed ML work (Parts 02–06) is kept as it is. The completed FastAPI service (Part 07) is kept as the **internal ML inference service**, because live features must come from the same Python module as training (Part 03 §6). Parts 07–09's application responsibilities (persistence, alerts, notifications, login) move to the Node.js API on MongoDB, which keeps the documented `/api/v1` contract. Each affected part has a **"Revision 2"** section with its own acceptance criteria. Original text and ticked checklists remain as the record of what was built. Decision record: `docs/decisions/0010-mern-application-layer.md`.
>
> **The Maharashtra place list is our proposed selection, not the examiner's.** The examiner asked for Maharashtra places and the map but gave no exhaustive list of cities or filters. Part 02 R2 proposes a configurable initial set, and Part 14 R2 proposes filters derived from data we already have.

---

## 1. System summary (derived from the project brief)

The product is a climate-intelligence web application with three cooperating subsystems:

1. **An ML pipeline** that ingests meteorological data and outputs a heatwave risk classification (Normal / Heatwave / Severe Heatwave) with a probability score.
2. **An explainability layer** (SHAP) that attaches a "why" to every prediction — the top contributing meteorological factors and their signed contribution.
3. **A full-stack web application** (FastAPI backend + SQLite + a frontend dashboard) that surfaces predictions, risk levels, explanations, alerts, and analytics to a Local Authority / Disaster Management Official, and that can push notifications (email/SMS/app) when a warning is issued.
   *(Revision 2: this is now a **MERN** application. A Node.js + Express API on MongoDB serves the React dashboard, owns login, alerts, notifications and analytics, and calls the FastAPI service for predictions. The dashboard adds an interactive Maharashtra map, and monitoring covers places across Maharashtra.)*

## 2. Reference architecture (from the project's own architecture diagram)

```
Weather Data Sources (IMD / NASA POWER / Dataset)
        │
        ▼
Data Preprocessing & Feature Engineering
        │
        ▼
ML Models (Logistic Regression / Random Forest / XGBoost)
        │
        ▼
Heatwave Prediction (Risk + Probability)
        │
        ▼
SHAP Explainability (Top Contributing Factors)
        │
        ▼
Backend API  ◄──────────────►  Database (SQLite)
        │
        ├──────────────► Notification Service (Email / SMS / App)
        │
        ▼
Web Dashboard (Frontend)
        │
        ▼
Local Authority / Disaster Management Official
```

Every box in this diagram maps to one or more plan files below.

### 2.1 Revision 2 architecture (MERN application layer + ML service)

The ML chain above is unchanged. The "Backend API ↔ Database" box splits into an application API and an internal ML service:

```
Weather Data Sources (IMD / NASA POWER / Open-Meteo forecast / synthetic)   (Part 02)
        │
        ▼
Preprocessing & Feature Engineering → ML Models → SHAP                      (Parts 03–06, Python)
        │
        ▼
ML Inference Service — FastAPI (internal only)                               (Part 07 §A)
  predict + SHAP factors + recommended actions, live features, model metadata
        ▲  internal HTTP (service token)
        │
Application API — Node.js + Express  ◄──────►  MongoDB                       (Part 07 §B, Part 08)
  login/users (15), predictions store, alerts (13)    users, places, predictions,
  analytics (14), map data (11), auto-draft rule      weather, alerts, deliveries,
        │                                             attempts, advisories
        ├──────────────► Notification Service — Node.js (Email / SMS / App)  (Part 09)
        │
        ▼
Web Dashboard — React (login, Maharashtra map, prediction, alerts, analytics) (Parts 10–14)
        │
        ▼
Local Authority / Disaster Management Official
```

Rules that keep this from becoming a redesign:
- **The React app talks only to the Node API**, which keeps the `/api/v1` contract already documented in `docs/api/README.md` (envelope, error taxonomy, field names). The Part 10 client and its contract tests carry over.
- **Only Python computes features, predictions and explanations.** The Node API never re-implements them. It stores and serves what the ML service returns.
- **Configuration stays in `config/`, read by both services:** regions/places, risk classes, alert channels, notification templates and recipients, and feature labels. Nothing is copied into Node code.

## 3. Full file index and what each one owns

| # | File | Owns |
|---|------|------|
| 01 | `01-environment-and-repo-setup.md` | Repo layout, tooling, config/secrets strategy, dev environment |
| 02 | `02-data-collection-pipeline.md` | IMD / NASA POWER ingestion, dataset acquisition, raw data storage |
| 03 | `03-data-preprocessing-feature-engineering.md` | Cleaning, feature engineering, synthetic dataset generation, train/test split |
| 04 | `04-model-development-training.md` | Training pipeline for LR / RF / XGBoost, hyperparameter strategy, artifact packaging |
| 05 | `05-model-evaluation-selection.md` | Metrics, comparison methodology, model selection, versioning/registry |
| 06 | `06-shap-explainability-integration.md` | SHAP integration into the inference path, output contract for "top factors" |
| 07 | `07-backend-api-architecture.md` | FastAPI service design, all endpoints, request/response contracts, error handling |
| 08 | `08-database-design.md` | SQLite schema, relationships, indexing, migration strategy |
| 09 | `09-notification-service.md` | Email/SMS/App delivery architecture, templating, retries, audit trail |
| 10 | `10-frontend-architecture-design-system.md` | Frontend stack, routing, shared components, design tokens, state management |
| 11 | `11-frontend-dashboard-overview-page.md` | Dashboard — Overview screen spec |
| 12 | `12-frontend-prediction-page.md` | Prediction — AI Model Output screen spec |
| 13 | `13-frontend-alerts-page.md` | Early Warning — Alert Management screen spec |
| 14 | `14-frontend-analytics-page.md` | Analytics — Trends & Insights screen spec |
| 15 | `15-authentication-authorization.md` | Login, roles, session handling, access control |
| 16 | `16-integration-and-data-flow.md` | End-to-end wiring of every part above into one working system |
| 17 | `17-testing-strategy.md` | Unit/integration/E2E test plan for both the ML side and the web app |
| 18 | `18-deployment-devops-monitoring.md` | Environments, CI/CD, hosting, observability, scaling |

**Revision 2 ownership changes** (each file's own "Revision 2" section has the detail):

| # | Adds or changes |
|---|---|
| 01 | `server/` workspace (Node.js 22 + TypeScript), local MongoDB, `server/.env.example` |
| 02 | Proposed, configurable Maharashtra place list (M3/M4), history and forecast pulls for those places |
| 03 | Normals for every place, synthetic generator v2 (per-place climate, plains zone) |
| 04–06 | Re-run on the v2 dataset (retrain → evaluate with per-zone metrics → promote → rebuild explainer). No method change |
| 07 | §A FastAPI becomes the internal ML inference service. §B new Node.js + Express application API (same `/api/v1` contract, batch and map-supporting endpoints) |
| 08 | MongoDB collections, indexes, validation, migrations, backups (M2). The SQLite design is retained as the reference model |
| 09 | Notification service ported to Node.js on MongoDB, plus the prediction → draft-alert rule (M5) |
| 10 | Map component, login page and route guard, API base URL → Node |
| 11 | Interactive Maharashtra map panel (M4) |
| 12 | Place selection across Maharashtra |
| 13 | Alerts on the Node/MongoDB service, model-suggested drafts (M5) |
| 14 | Place and division analysis with our proposed filters (M3) |
| 15 | Login implemented in Node.js + MongoDB, required for the app, with logout (M1) |
| 16–18 | Checkpoints, tests and deployment for three services + MongoDB |

## 4. Recommended build order and dependency graph

Parts must respect these dependencies. Anything not listed as a dependency can, in principle, be parallelized across team members.

```
01 (env/repo)
 └─► 02 (data collection)
      └─► 03 (preprocessing/features)
           └─► 04 (model training)
                └─► 05 (evaluation/selection)
                     └─► 06 (SHAP)
                          └─► 07 (backend API)   ◄── 08 (database, can start in parallel with 07)
                               ├─► 09 (notifications)
                               ├─► 15 (auth)
                               └─► 10 (frontend architecture)
                                    ├─► 11 (dashboard page)
                                    ├─► 12 (prediction page)
                                    ├─► 13 (alerts page)
                                    └─► 14 (analytics page)
                                         └─► 16 (integration)
                                              └─► 17 (testing)
                                                   └─► 18 (deployment)
```

Practical grouping for a small team of 3 (matching the project's authorship):
- **Person A (Data/ML):** 02 → 03 → 04 → 05 → 06
- **Person B (Backend):** 01 → 08 → 07 → 09 → 15
- **Person C (Frontend):** 10 → 11 → 12 → 13 → 14
- **All together:** 16 → 17 → 18

### 4.0 Implementation status board (kept current: update with every step)

What is **actually built**, checked against the code. "Built" means implemented and tested in the working tree. "Uncommitted" means it is not yet in git history. Teacher requirements: M1 login · M2 MongoDB · M3 Maharashtra analysis · M4 Maharashtra map · M5 Node.js + MongoDB alerts.

| Part | Original plan | Revision 2 | Teacher req. |
|---|---|---|---|
| 01 Env & repo | ✅ Built (`main`). Open: human runbook dry run | ✅ **Step 1 built** (uncommitted): `server/` skeleton, local MongoDB, pre-commit hooks. Open: human runbook dry run | M2 groundwork |
| 02 Data collection | ✅ Built (`main`) | 🟡 **Steps 2–3 built** (uncommitted): loaders; our proposed 18 Maharashtra places; real IMD 1991–2024, NASA POWER 2000–2024 and forecast pulled, 0 gaps. ⏳ 6-hourly refresh (step 6) | M3, M4 |
| 03 Preprocessing | ✅ Built (`main`) | 🟡 **Step 3 built** (uncommitted): normals for 18 places (original rows byte-identical), v1 training scope pinned. ⏳ History export (step 9), generator v2 (step 10) | M3 |
| 04–06 Model, evaluation, SHAP | ✅ Built (`main`); production model `xgboost-20260928T100821Z-0bde51` | ⏳ Not started (step 10: retrain on Maharashtra data) | M3, M4 accuracy |
| 07 Backend API | ✅ Built in FastAPI (`main`) | 🟡 **§A built** (step 2); **§B places/weather/predictions** (step 4) and **login + frontend switched to Node** (step 5); uncommitted. ⏳ Alerts (8), analytics + generated OpenAPI (9) | M1, M2, M5 |
| 08 Database | ✅ Built in SQLite (`main`) | 🟡 **MongoDB in use** (step 4, uncommitted): migrations + 4 collections with validators and indexes. ⏳ Users (5), alerts (8), history (9), backups (11) | **M2** |
| 09 Notifications | ✅ Built in Python (`main`) | 🟡 **Node.js + MongoDB alerts built, mock delivery** (scope freeze, uncommitted) | **M5** |
| 10 Frontend foundation | ✅ Built (uncommitted, branch `part-10/frontend-architecture`) | 🟡 **Login page, guard, token on every call, Node base URL built** (step 5, uncommitted). ⏳ Map + place grouping (step 6) | M1, M4 |
| 11 Dashboard | ✅ **Built with the Maharashtra map** (step 6, uncommitted) | ✅ map, layers, table, score button, refresh script | **M4** |
| 12 Prediction page | ✅ **Built, minimal** (uncommitted) | ✅ any place, SHAP, inland caveat | M4 |
| 13 Alerts page | ✅ **Built, minimal** (uncommitted) | ✅ create / issue / track (mock delivery) | **M5** |
| 14 Analytics page | ✅ **Built, minimal** (uncommitted) | ✅ real IMD history 2000–2024, comparison, model metrics | **M3** |
| 15 Auth | 🟡 Partly built inside Parts 07/08/10 (FastAPI reference) | 🟡 **Built on Node + MongoDB** (step 5, uncommitted): login required everywhere, logout with revocation, lockout, account CLI, login page; verified live in a browser. ⏳ Expiry warning; "Issue Warning" gating (step 8) | **M1** |
| 16 Integration | ⏳ Not started | ⏳ Not started (step 11) | all |
| 17 Testing | 🟡 Unit tests exist for Parts 02–10 (and the server skeleton); no E2E, no CI | ⏳ Not started (step 11) | all |
| 18 Deployment | ⏳ Not started (only a PR template in `.github/`; no CI workflows) | ⏳ Not started (step 11) | — |

**Current test totals (after the scope freeze, 2026-10-20):** Python 337 passed, 3 skipped, 6 errors (the known issue below) · frontend 174 · server 150. **End-to-end demo passed in a real browser:** login → map → place → prediction → analysis → alert issued and delivered (mock).

**Scope frozen 2026-10-20 (owner):** all five mandatory features (M1–M5) are built and demonstrated. Steps 10 (retrain on Maharashtra data) and 11 (formal integration suite, CI, deployment) are **not done**; the inland-model caveat stays on screen until step 10.

**Known baseline issue (2026-10-20):** on the development Mac the Python suite reports **6 errors**, all in `backend/tests/test_production_model.py`. Its skip guard checks only that `ml/artifacts/runs/` exists, and a local, non-production training run now exists there. This is not a code defect in the app (runbook, Troubleshooting).

### 4.1 Revision 2 build sequence (from the state on 2026-10-20)

Done before Revision 2: Parts 01–09 (FastAPI + SQLite) and Part 10 (frontend foundation). **Not yet built:** the four pages (Parts 11–14) and Parts 16–18. Each page is built once, to its original spec plus its Revision 2 section.

Revision 2 proceeds in **small steps**. Each step is merged and validated against the running application before the next starts, and at every step the current app keeps working.

| Step | Parts | What lands | Validate before moving on | Depends on |
|---|---|---|---|---|
| **1** ✅ built 2026-10-20 | 01 R2 | `server/` skeleton (Express + TypeScript, `/health`), local MongoDB, env template, lint/test scripts. Nothing switched | existing Python (290) and frontend (145) suites green; server skeleton tests green; runbook steps work on a clean machine | none |
| **2** ✅ built 2026-10-20 | 02 R2 (loader fix), 07 §A (role `ml`, `/predict/batch`, `/model`) | the two Python loaders accept the new optional region fields; FastAPI gains the ML-service role and two additive endpoints | all existing backend and ML tests green; `SERVICE_ROLE=app` behaves exactly as before | 1 |
| **3** ✅ built 2026-10-20 | 02 R2, 03 R2.1 | the proposed places in `regions.yaml` **with** their normals (existing five rows byte-identical), history and forecast pulls, the forecast sample for every place | current model still loads; explainer verify passes; every place scores through the ML service; v1 dataset still builds | 2 |
| **4** ✅ built 2026-10-20 | 08 R2, 07 §B (places, predictions, weather) | MongoDB collections and migrations; Node API: regions, weather, predict, batch, latest-by-region, `score-all`, readiness. Frontend still on FastAPI | server integration tests (in-memory MongoDB, fake ML service); a stored prediction equals the ML service's output field for field (checkpoint 3.7) | 2, 3 |
| **5** ✅ built 2026-10-20 | 15 R2, 10 R2.1, 07 §B transition | login, logout and accounts in Node; the frontend login page and route guard; **frontend switched to the Node API** | frontend contract and component tests against the Node `openapi.json`; login → shell → logout works; first E2E smoke | 4 |
| **6** ✅ built 2026-10-20 (frozen scope) | 10 R2.2–R2.3, 11 (+R2), 02 R2.3b | `MaharashtraMap`; the dashboard built to Part 11 with the map, layers, table, score-missing button; 6-hourly refresh | the Part 11 criteria; number consistency map ↔ table ↔ cards; the map shows current forecast data, not the sample | 5 |
| **7** ✅ built 2026-10-20 (frozen scope) | 12 (+R2) | the Prediction page for any place | Part 12 criteria, including negative SHAP bars and drill-through from the map | 6 |
| **8** ✅ built 2026-10-20 (frozen scope) | 09 R2, 13 (+R2) | Node notifications (parity port) and the draft-suggestion rule; the Alerts page | ported notification tests green; suggested draft → issue → statuses update on screen (checkpoint 3.9) | 5, 7 |
| **9** ✅ built 2026-10-20 (frozen scope) | 03 R2.3 export, 14 (+R2) | observed-history export and import; the Analytics page A1–A10 | Part 14 criteria; one place's figures match a hand-run aggregation | 3, 4, 6 |
| **10** | 03 R2.2–R2.3, 04–06 R2 | generator v2, retrain, per-zone evaluation, promotion, explainer rebuild on the designated platform | per-zone gates pass; the inland caveat removed from map and analysis | 3 (can run in parallel with steps 4–9) |
| **11** | 16 → 17 → 18 R2 | integration checkpoints, the full test layers, deployment | checkpoints 3.7–3.12; FastAPI `app` role retired from deployment | 1–10 |

- **Steps 1–5 change nothing a user sees** except the login page in step 5. That gives five checkpoints where the existing app can be compared before and after.
- **The ML track (step 10) does not block the app track.** The map and analysis work with the current model, carrying the inland caveat until step 10 lands.
- **The examiner demo path** (login → Maharashtra map → place → analysis → suggested draft → issue → delivery status) is complete after step 9.

### 4.2 Existing implementation that Revision 2 modifies (conflict register)
| # | Existing (built) | Conflict | Resolution | Step |
|---|---|---|---|---|
| C1 | `Region(**entry)` (ml ingestion) and `RegionInfo(**r)` (FastAPI catalog) build regions strictly from YAML keys | new `division`/`kind`/`parent` keys would crash ingestion and the API at startup | add them as optional fields; still reject unknown keys | 2 |
| C2 | `config/seasonal_normals.csv` (5 places) used by the production model, the explainer and the v1 dataset | rebuilding it could change existing rows | extend for new places only; existing rows byte-identical (asserted). Nothing pins the file hash, and the dataset check is per row | 3 |
| C3 | Auth matrix: all GETs and `POST /predict` open (Part 07) | Revision 2 requires login for every data endpoint | enforced in the Node API only; the frontend's read hooks attach the token; FastAPI `app` role unchanged until retired | 5 |
| C4 | Alerts, notifications and login implemented and tested in Python | Node re-implements them (M5, M1) | Python is the specification; tests ported; the Python `app` role is frozen (fixes only) during the transition, then retired, not deleted | 4–8 |
| C5 | `docs/api/openapi.json` generated from FastAPI, read by the frontend contract test | Node becomes the public contract | Node generates `openapi.json`; FastAPI's moves to `ml-service-openapi.json` | 5 |
| C6 | SQLite application store (Part 08) | MongoDB is the store (M2) | the SQLite schema stays as reference; local SQLite demo data is not migrated (optional import) | 4 |
| C7 | Production model `xgboost-20260928T100821Z-0bde51`, trained on coastal Mumbai synthetic data | inland risk needs retraining; numbers on every page change at promotion | caveat until step 10; the old model stays archived as the rollback target; promotion is its own event | 10 |
| C8 | "Bit-for-bit reproducible" training (Part 04) | not reproducible across platforms (Apple Silicon vs Windows/x86) | designated training platform; the bundle is shipped as an artifact | 10 |
| C9 | The forecast file is a committed sample from 2026-09-28 | the map must show actual current data | 6-hourly refresh through the existing scheduled-pull path | 6 |
| C10 | `data/raw/` is git-ignored and empty on a fresh machine | normals and analysis need the landed IMD and NASA history | re-pull (resumable; the IMD host is unreliable, so budget time) | 3 |
| C11 | Real history resolves the Mumbai areas to only 2 IMD cells | per-area historical analysis would look independent when it is not | shared-cell disclosure in the analysis | 9 |
| C12 | `frontend/.env.example`, `VITE_API_BASE_URL` → FastAPI `:8000` | Node API on `:4000` | switched once, in step 5 | 5 |

## 5. Cross-cutting decisions locked in across all parts

These decisions are referenced by multiple downstream files, so they are fixed here once rather than repeated:

- **Backend framework:** FastAPI (Python), as shown in the architecture diagram.
- **Database:** SQLite for this project's scale (single-node, demo/mini-project scope), with the schema written so it can migrate to PostgreSQL later without a redesign (see file 08).
- **ML stack:** scikit-learn (Logistic Regression, Random Forest) + XGBoost, with SHAP for explainability.
- **Three risk classes:** `NORMAL`, `HEATWAVE`, `SEVERE_HEATWAVE` — this exact vocabulary is used everywhere (database enum, API contract, frontend labels) to avoid drift between layers.
- **Time horizon:** predictions are short-term (next 1–3 days), which affects how the frontend labels forecasts and how often the pipeline needs to re-run.
- **Primary consumer/persona:** a Local Authority / Disaster Management Official — every UX decision in files 11–14 is written for this persona, not the general public.
- **Explainability is not optional:** every prediction returned by the API must carry its SHAP-derived top factors in the same response — this is treated as a core contract, not an add-on endpoint.

**Revision 2 (2026-10-20) updates these decisions.** Where they conflict with the list above, the following wins:

- **Application stack: MERN.** MongoDB, Express on Node.js 22 (TypeScript), React (Part 10's Vite + React 19 frontend). The Node.js API in `server/` is the only backend the frontend calls.
- **ML inference service: FastAPI (Python)**, the existing Part 07 service in `backend/`, internal only. It owns live feature computation, prediction, SHAP and the recommended-action mapping. Training, evaluation and SHAP stay scikit-learn + XGBoost + SHAP (unchanged).
- **Database: MongoDB** for all application data (users, places, predictions, weather snapshots, alerts, deliveries, notification audit, advisories, model metadata), Part 08 R2. The SQLite schema from Part 08 remains the reference model it was ported from and is no longer the application's store.
- **Monitored places: across Maharashtra**, configurable in `config/regions.yaml`. The initial set is **our proposal** (Part 02 R2), not an examiner-specified list.
- **Login is required** for every application page and data endpoint. Health checks and the public advisory feed stay open (Part 15 R2).
- **Alerts are created by people or suggested by the model, and issued only by people.** A HEATWAVE/SEVERE_HEATWAVE prediction may create a *draft*. Nothing is dispatched until an official issues it (Part 09 R2).
- **The API contract is preserved:** the Node API serves the `/api/v1` contract in `docs/api/README.md` (envelope, error taxonomy, the three risk classes, field names) and extends it additively.

## 6. How to use this file set with an AI coding agent

If you hand these to a coding assistant (e.g., Claude Code) one at a time:
1. Paste the master plan (this file) once at the start of the project so the agent has the full map.
2. Then feed each numbered file **in dependency order** as its own task/session.
3. At the end of each part, ask the agent to produce a short "handoff note" (what was built, what the next part can assume exists) before moving to the next file — this keeps context manageable across sessions.
4. **After every major change, write a detailed implementation log in `docs/logs/`** (one per part, `NN-<plan-file-slug>.md`; other major changes `YYYY-MM-DD-<slug>.md`) using the template in `docs/logs/README.md`, and add it to that index. The plans say what *should* be built; the logs record what *was* built, why, how it was verified, and what is still open.
5. Re-paste this master file if you switch to a new chat/session partway through, so the agent re-orients itself.

## 7. Definition of "done" for the whole project

The project is complete when:
- A request to the prediction endpoint returns a risk class, probability, and SHAP top factors in one response (files 04–07).
- That prediction is persisted and retrievable (file 08).
- An authority user can log in, view the dashboard, drill into a prediction, issue an alert, and view historical analytics (files 10–15).
- Issuing an alert triggers a notification through at least one channel (file 09).
- The system has automated tests covering the ML pipeline and the API/frontend (file 17).
- The system can be deployed to a reproducible environment from a clean checkout (file 18).

Revision 2 adds these to the definition of done (the examiner's mandatory features):
- **M1:** an official cannot see any application page or data without signing in, and can sign out. Credentials live in MongoDB as salted hashes (file 15).
- **M2:** all application data is stored in and read from MongoDB, with indexes, validation, migrations and a tested backup/restore (file 08).
- **M3:** the Analytics page analyses 1991–2024 observed weather history, heatwave patterns (frequency and trend, season, spells, extremes) and stored predictions (risk distribution, forecast stability) for any selected Maharashtra place. Users can compare places across a division and side by side, reached from the dashboard, and observed and predicted data are never mixed (file 14).
- **M4:** the dashboard shows an interactive Maharashtra map of every monitored place from our actual forecast data and stored predictions: predicted risk, forecast maximum temperature or departure from normal per lead day, with freshness shown. Selecting a place drives the rest of the dashboard and leads into its analysis (file 11).
- **M5:** alerts are created, suggested from predictions, issued and tracked per channel by the Node.js service on MongoDB, and issuing triggers at least one delivery channel (files 09, 13).
