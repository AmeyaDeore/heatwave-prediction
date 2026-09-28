These decisions are referenced by multiple downstream files, so they are fixed here once rather than repeated:

Backend framework: FastAPI (Python), as shown in the architecture diagram.
Database: SQLite for this project's scale (single-node, demo/mini-project scope), with the schema written so it can migrate to PostgreSQL later without a redesign (see file 08).
ML stack: scikit-learn (Logistic Regression, Random Forest) + XGBoost, with SHAP for explainability.
Three risk classes: NORMAL, HEATWAVE, SEVERE_HEATWAVE — this exact vocabulary is used everywhere (database enum, API contract, frontend labels) to avoid drift between layers.
Time horizon: predictions are short-term (next 1–3 days), which affects how the frontend labels forecasts and how often the pipeline needs to re-run.
Primary consumer/persona: a Local Authority / Disaster Management Official — every UX decision in files 11–14 is written for this persona, not the general public.
Explainability is not optional: every prediction returned by the API must carry its SHAP-derived top factors in the same response — this is treated as a core contract, not an add-on endpoint.
