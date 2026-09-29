# AI Heatwave Prediction & Early Warning System — Master Implementation Plan

## Purpose of this document set

This is not a single build prompt. It is a **sequenced set of standalone implementation plans**, one per `.md` file, each scoped tightly enough to be executed on its own (by a human developer or an AI coding agent) without needing every other file open at once. Each file states its own inputs, outputs, and "done" criteria so it can be picked up independently, in order.

Read this file first. It explains the system as a whole, the build order, and how the parts hand off to each other. No code appears anywhere in this set — only specifications, contracts, decisions, and step-by-step task breakdowns. Writing the actual code from each plan is a separate, later activity.

---

## 1. System summary (derived from the project brief)

The product is a climate-intelligence web application with three cooperating subsystems:

1. **An ML pipeline** that ingests meteorological data and outputs a heatwave risk classification (Normal / Heatwave / Severe Heatwave) with a probability score.
2. **An explainability layer** (SHAP) that attaches a "why" to every prediction — the top contributing meteorological factors and their signed contribution.
3. **A full-stack web application** (FastAPI backend + SQLite + a frontend dashboard) that surfaces predictions, risk levels, explanations, alerts, and analytics to a Local Authority / Disaster Management Official, and that can push notifications (email/SMS/app) when a warning is issued.

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

## 5. Cross-cutting decisions locked in across all parts

These decisions are referenced by multiple downstream files, so they are fixed here once rather than repeated:

- **Backend framework:** FastAPI (Python), as shown in the architecture diagram.
- **Database:** SQLite for this project's scale (single-node, demo/mini-project scope), with the schema written so it can migrate to PostgreSQL later without a redesign (see file 08).
- **ML stack:** scikit-learn (Logistic Regression, Random Forest) + XGBoost, with SHAP for explainability.
- **Three risk classes:** `NORMAL`, `HEATWAVE`, `SEVERE_HEATWAVE` — this exact vocabulary is used everywhere (database enum, API contract, frontend labels) to avoid drift between layers.
- **Time horizon:** predictions are short-term (next 1–3 days), which affects how the frontend labels forecasts and how often the pipeline needs to re-run.
- **Primary consumer/persona:** a Local Authority / Disaster Management Official — every UX decision in files 11–14 is written for this persona, not the general public.
- **Explainability is not optional:** every prediction returned by the API must carry its SHAP-derived top factors in the same response — this is treated as a core contract, not an add-on endpoint.

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
