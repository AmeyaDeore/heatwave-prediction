# backend/

FastAPI service (Parts 07–09, 15). Every prediction response carries its SHAP top factors, and the risk classes are exactly `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`.

- Package: `src/heatwave_api/`.
  - `app.py` is the factory (startup checks, middleware, error handlers), `main.py` the entry point, `config.py` the typed settings.
  - `routes.py` has every endpoint, `schemas.py` the contracts, `errors.py` the error taxonomy, `envelope.py` the response shape.
  - `predictor.py` loads the production model and explainer, `weather.py` reads the pipeline's conditions, `alerts.py` is the DRAFT → READY → ISSUED flow. `auth.py`, `ratelimit.py`, `notifier.py` (Part 09 seam) and `repositories.py` (the persistence protocol) round it out.
  - `db/` is the SQLite layer (Part 08): `migrations/NNNN_*.sql`, `migrate.py`, `repository.py` (`SqliteRepository`, `SqliteUserStore`), `cli.py` (`heatwave-db`).
- Contract, decisions and limits: [docs/api/README.md](../docs/api/README.md). Schema, migrations, backups: [docs/database/README.md](../docs/database/README.md).
- Tests: `tests/`
- Config: copy `.env.example` to `.env`.

```sh
uv sync --package heatwave-api
uv run uvicorn heatwave_api.main:app --reload     # http://localhost:8000/health, docs at /docs
                                                  # needs the trained bundles: uv run heatwave-train run
uv run pytest backend/tests                       # in-memory SQLite, never touches data/local/

uv run heatwave-db status                         # migration version + row counts (local migrates itself at startup)
uv run heatwave-db backup                         # consistent copy into data/local/backups/
```
