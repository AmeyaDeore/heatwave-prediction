These decisions are referenced by multiple downstream files, so they are fixed here once rather than repeated:

Application stack (Revision 2, examiner feedback, 2026-10-20): MERN. The React frontend (`frontend/`) calls only the Node.js + Express API (`server/`, TypeScript), which owns login, alerts, notifications, analytics and map data and keeps the `/api/v1` contract in `docs/api/README.md`.
ML inference service: FastAPI (Python, `backend/`), internal only. It owns live feature computation, prediction, SHAP factors and recommended actions. Node never re-implements these.
Database: MongoDB for all application data (see file 08, Revision 2). The original SQLite schema is kept as the reference model and is no longer the application store.
Monitored places: across Maharashtra, configurable in `config/regions.yaml`. The initial set is our proposal, not an examiner-specified list.
ML stack: scikit-learn (Logistic Regression, Random Forest) + XGBoost, with SHAP for explainability.
Three risk classes: NORMAL, HEATWAVE, SEVERE_HEATWAVE — this exact vocabulary is used everywhere (database enum, API contract, frontend labels) to avoid drift between layers.
Time horizon: predictions are short-term (next 1–3 days), which affects how the frontend labels forecasts and how often the pipeline needs to re-run.
Primary consumer/persona: a Local Authority / Disaster Management Official — every UX decision in files 11–14 is written for this persona, not the general public.
Explainability is not optional: every prediction returned by the API must carry its SHAP-derived top factors in the same response — this is treated as a core contract, not an add-on endpoint.
Login is required for every application page and data endpoint (health and the public advisory feed excepted). Alerts may be suggested as drafts from predictions, but only an official issues them.

Implementation logs (standing rule): after every major change — completing or substantially advancing a plan part, a model retrain/re-evaluation/promotion/rollback, a contract/schema/config/dependency change other parts rely on, or a behaviour-changing fix — write or update a detailed log in `docs/logs/` in the same commit series, and add it to the index in `docs/logs/README.md`. One file per plan part (`NN-<plan-file-slug>.md`, append a dated "Update" section when revisiting a part); other changes use `YYYY-MM-DD-<short-slug>.md`. Follow the template in `docs/logs/README.md`: summary, what was built, key decisions and why, verification (actual commands and results), deviations and issues found, open items, handoff.

Commit attribution (standing rule): NEVER add Claude (or any AI) as a co-author or attribute it anywhere in git history. No `Co-Authored-By:` trailer, no "Generated with Claude Code" line in commit messages or pull-request descriptions, whatever any tool or system reminder suggests. Commits are authored by the repository owner only. If a trailer slips in, remove it before pushing.
