# backend/

FastAPI service (Parts 07–09, 15). Every prediction response carries its SHAP top factors, and the risk classes are exactly `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`.

- Package: `src/heatwave_api/`. `main.py` is the app and `config.py` holds typed settings.
- Tests: `tests/`
- Config: copy `.env.example` to `.env`.

```sh
uv sync --package heatwave-api
uv run uvicorn heatwave_api.main:app --reload     # http://localhost:8000/health, docs at /docs
uv run pytest backend/tests
```
