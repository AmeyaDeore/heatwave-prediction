# AI Heatwave Prediction & Early Warning System

Predicts short-term (1–3 day) heatwave risk (`NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`) with SHAP explanations, and helps Local Authority / Disaster Management Officials issue early warnings.

```
data/       datasets (raw/processed git-ignored; sample/ committed)
ml/         ingestion, preprocessing, training, evaluation, SHAP        (Parts 02–06)
backend/    FastAPI service + SQLite                                     (Parts 07–09, 15)
frontend/   web dashboard                                                (Parts 10–14)
config/     shared non-secret config (risk classes, regions)
docs/       runbook, config/secrets guide, decision records
deploy/     deployment manifests                                         (Part 18)
tests/      cross-cutting integration / E2E tests                        (Parts 16–17)
Implementation/   the 18-part implementation plan
```

## Quick start

Requires Python 3.13 (via [uv](https://docs.astral.sh/uv/)) and Node 22.

```sh
uv sync --all-packages && uv run pre-commit install
(cd frontend && npm ci)
cp backend/.env.example backend/.env && cp ml/.env.example ml/.env && cp frontend/.env.example frontend/.env.local
uv run uvicorn heatwave_api.main:app --reload     # → http://localhost:8000/health
```

The full walkthrough is in [docs/local-dev-runbook.md](docs/local-dev-runbook.md). Conventions are in [CONTRIBUTING.md](CONTRIBUTING.md).
