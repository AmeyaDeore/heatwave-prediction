# backend/

FastAPI service (Part 07; Parts 08, 09 and 15 build on it). Every prediction response carries its SHAP explanation, and the risk classes are exactly `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`.

- **Contract:** [`docs/api/README.md`](../docs/api/README.md) and the generated [`docs/api/openapi.json`](../docs/api/openapi.json). Decisions are in [ADR 0006](../docs/decisions/0006-backend-api.md).
- **Config:** copy `.env.example` to `.env`. The defaults work locally.

```sh
uv sync --package heatwave-api                    # pulls in heatwave-ml (features, registry, explainer)
uv run heatwave-train run                         # fresh clone only: rebuild the git-ignored model bundles
uv run heatwave-api check                         # full startup check without serving
uv run heatwave-api create-user duty --display-name "Duty Officer"   # prompts for a password
uv run uvicorn heatwave_api.main:app --reload     # http://localhost:8000/docs
uv run pytest backend/tests
uv run heatwave-api openapi                       # after any contract change: regenerate docs/api/openapi.json
```

## Layout (`src/heatwave_api/`)

| Module | Role |
|---|---|
| `main.py` | App factory: lifespan (fail-fast startup), CORS, request-id and logging middleware, `/health` |
| `api.py` | The `/api/v1` routes. Thin: validate, delegate, wrap in the envelope |
| `schemas.py` | Every request and response body (the contract), plus the envelope |
| `errors.py`, `responses.py` | The error taxonomy (client/auth/upstream/internal), and the envelope for every failure |
| `services.py`, `deps.py` | The startup container, and per-request dependencies (DB connection, current user, rate limits) |
| `inference.py` | Loads the production model and explainer once, and runs `build_features` then `explain` |
| `weather.py` | The live forecast through Part 02's Open-Meteo adapter, cached in `weather_snapshots` |
| `predictions.py`, `alerts.py`, `analytics.py` | Endpoint logic: prediction runs, the alert status flow and dispatch, analytics and current weather |
| `actions.py` | The deterministic recommended-actions mapping (`config/recommended_actions.yaml`) |
| `notifications.py` | The `Notifier` boundary to Part 09, and the mock notifier |
| `security.py`, `ratelimit.py`, `observability.py` | Tokens and password hashes, rate limits, JSON logs |
| `db/` | SQLite connection, numbered SQL migrations (`migrations/`), and the `Repository` (all SQL) |
| `cli.py` | `heatwave-api migrate · create-user · set-password · check · openapi` |

Tests (`tests/`) run the real app and the real startup against a fake model, a fake forecast and the mock notifier, with a fresh SQLite file per test. `test_production_model.py` also runs the real production model and explainer through the API, and is skipped until the bundles are rebuilt.
