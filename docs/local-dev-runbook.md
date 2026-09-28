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
- **ML track:** run the Part 02 ingestion to fill `data/raw/` (Part 03 then fills `data/processed/`):
  ```sh
  uv run heatwave-ingest synthetic                        # seconds
  uv run heatwave-ingest forecast                         # seconds
  uv run heatwave-ingest historical --source nasa_power   # ~1 min, resumable
  uv run heatwave-ingest historical --source imd          # ~30 min, resumable; see docs/data/raw-landing-zone.md if IMD is unreachable
  uv run heatwave-ingest status
  ```
- **Backend/frontend track:** use the committed `data/sample/` dataset, so you are not blocked on ML work.

## 6. Start the backend

```sh
uv run uvicorn heatwave_api.main:app --reload
```

Check it: http://localhost:8000/health should return `{"status":"ok","env":"local"}`. Interactive docs are at http://localhost:8000/docs.

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
