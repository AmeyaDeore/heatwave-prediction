# Local development runbook

Goal: go from `git clone` to a running system in under 30 minutes. Commands are written for Git Bash / macOS / Linux. PowerShell equivalents are given where they differ.

> **Validation status:** Steps 1–6 were checked by the author on Windows 11 on 2026-09-28. Steps 7–8 cannot be checked until Parts 07 and 10 exist. **A second contributor must dry-run the full runbook** once those parts land. Record the result in the table at the bottom.

## 1. Install pinned runtimes

| Tool | Version | Pinned in | Install |
|------|---------|-----------|---------|
| Python | 3.13.x | `.python-version`, `requires-python` | `uv python install` (reads `.python-version`) |
| uv | ≥ 0.12 | `[build-system]` in member pyprojects | https://docs.astral.sh/uv/getting-started/installation/ |
| Node.js | 22.x | `.nvmrc`, `frontend/package.json` engines | `nvm use` or https://nodejs.org |
| Git | any recent | – | – |

## 2. Python environment (ml/ + backend/)

```sh
uv sync --all-packages          # creates .venv/ at repo root from uv.lock
uv run pre-commit install       # enables commit-time format/lint/secret checks
```

Working on only one side? Run `uv sync --package heatwave-api` for backend only, or `uv sync --package heatwave-ml` for ML only. Frontend-only contributors can skip this step, apart from the pre-commit hooks.

## 3. Frontend dependencies

```sh
cd frontend && npm ci && cd ..
```

## 4. Local config

```sh
cp backend/.env.example backend/.env
cp ml/.env.example ml/.env
cp frontend/.env.example frontend/.env.local
```

PowerShell: `Copy-Item backend/.env.example backend/.env` (and likewise for the others).

The defaults work locally as they are. SQLite writes to `data/local/heatwave.db`, notifications run in `mock` mode, and NASA POWER needs no API key. For anything beyond your own machine, generate a real `AUTH_SECRET_KEY`.

## 5. Data

Choose one:
- **ML track:** the modelling dataset `data/heatwave_dataset.csv` and the seasonal normals are committed, so training (Part 04) can start straight away. To rebuild everything from source, run the Part 02 ingestion to fill `data/raw/`, then the Part 03 preparation:
  ```sh
  uv run heatwave-ingest forecast                         # seconds
  uv run heatwave-ingest historical --source nasa_power   # ~1 min, resumable
  uv run heatwave-ingest historical --source imd          # ~30 min, resumable; see docs/data/raw-landing-zone.md if IMD is unreachable
  uv run heatwave-ingest status
  uv run heatwave-prepare all                             # normals → dataset → observed → sample (docs/data/preprocessing.md)
  ```
  `heatwave-prepare dataset` needs only the committed `config/seasonal_normals.csv`: it generates and lands the synthetic batch itself, with no network access.

  Then train the three candidate models (Part 04; about 45 s, offline). The bundles are git-ignored, so every fresh clone runs this once:
  ```sh
  uv run heatwave-train run       # → ml/artifacts/runs/<run_id>/ (docs/ml/training.md)
  uv run heatwave-train verify
  ```
- **Backend/frontend track:** use the committed `data/sample/` dataset, so you are not blocked on ML work.

## 6. Start the backend

The backend loads the production model and its SHAP explainer at startup, and refuses to start without them. On a fresh clone, run `uv run heatwave-train run` (step 5) first. Then:

```sh
uv run heatwave-api check                  # optional: runs the full startup and reports
uv run heatwave-api create-user duty --display-name "Duty Officer"   # prompts for a password
uv run uvicorn heatwave_api.main:app --reload
```

The database (`data/local/heatwave.db`) is created and migrated on first start. Check it:
- http://localhost:8000/health returns `{"status":"ok","env":"local"}` (liveness);
- http://localhost:8000/api/v1/health reports the model version and explainer id (readiness);
- interactive docs are at http://localhost:8000/docs, and the contract is [docs/api/README.md](api/README.md).

`POST /api/v1/predict` fetches the live Open-Meteo forecast, so it needs internet access. To work offline, send the weather yourself with `conditions` (see the contract).

## 7. Start the frontend *(available after Part 10)*

```sh
cd frontend && npm run dev      # expected at http://localhost:5173
```

## 8. Verify end-to-end *(available after Parts 07 + 10)*

Open http://localhost:5173. The dashboard should show sample predictions for the regions in `config/regions.yaml`, with no CORS errors in the browser console.

## Quality checks (run before pushing)

```sh
uv run pre-commit run --all-files
uv run pytest
```

## Troubleshooting

- **`uv` picks the wrong Python:** run `uv python install 3.13`, then `uv sync --all-packages` again.
- **Pre-commit frontend hooks fail with "eslint not found":** run `npm ci` inside `frontend/`.
- **OneDrive-synced checkout is slow or locks files:** clone outside OneDrive, or exclude `.venv/` and `node_modules/` from sync.

## Validation log

| Date | Who | OS | Steps passed | Notes |
|------|-----|----|--------------|-------|
| 2026-09-28 | Author (setup) | Windows 11 | 1–6 | Initial skeleton |
| 2026-09-28 | Claude Code (automated dry run, **not** a second person) | Windows 11 | 1–4, 6 | Clean export of the staged tree (`git checkout-index`) into an empty directory. `uv sync`, `npm ci`, env copies, `pytest` and `/health` all passed from scratch in about 16 s with warm caches. The pre-commit secret hook blocked a planted fake AWS key (exit 1). |
| | *second contributor* | | | **Required before Part 01 is "done"** |
