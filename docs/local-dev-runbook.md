# Local development runbook

Goal: go from `git clone` to a running system in under 30 minutes. Commands are written for Git Bash / macOS / Linux. PowerShell equivalents are given where they differ.

> **Validation status:** Steps 1–6 were checked by the author on Windows 11 on 2026-09-28. Step 6 was extended in Part 07 and checked on 2026-09-29. Steps 7–8 were added in Part 10 and checked on macOS on 2026-10-20 (see the validation log). **A second contributor must dry-run the full runbook** once those parts land. Record the result in the table at the bottom.

## 1. Install pinned runtimes

| Tool | Version | Pinned in | Install |
|------|---------|-----------|---------|
| Python | 3.13.x | `.python-version`, `requires-python` | `uv python install` (reads `.python-version`) |
| uv | ≥ 0.12 | `[build-system]` in member pyprojects | https://docs.astral.sh/uv/getting-started/installation/ |
| Node.js | 22.x (≥ 22.9) | `.nvmrc`, `frontend/` and `server/` `package.json` engines | `nvm use` or https://nodejs.org |
| MongoDB | 7.0.x | Revision 2 (Part 01 R2); container image tag or local install | step 6a |
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
cd server && npm ci && cd ..      # Node.js application API (Revision 2)
```

## 4. Local config

```sh
cp backend/.env.example backend/.env
cp ml/.env.example ml/.env
cp frontend/.env.example frontend/.env.local
cp server/.env.example server/.env    # optional: the server's defaults are the local values
```

PowerShell: `Copy-Item backend/.env.example backend/.env` (and likewise for the others).

The defaults work locally as they are. SQLite writes to `data/local/heatwave.db`, notifications run in `mock` mode (logged, never sent; recipients ending `.fail`/`.retry` simulate provider failures, docs/notifications §2), and NASA POWER needs no API key. For anything beyond your own machine, generate a real `AUTH_SECRET_KEY`.

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

```sh
uv run uvicorn heatwave_api.main:app --reload
```

The model and explainer load at startup, so step 5's `heatwave-train run` (the git-ignored bundles) must have run first. Without them the service refuses to start and says why.

Check it: http://localhost:8000/health should return `{"status":"ok","env":"local"}`, and http://localhost:8000/api/v1/health/ready should report the model version and `weather_data`. Interactive docs are at http://localhost:8000/docs. The full contract is [api/README.md](api/README.md).

```sh
curl -s -X POST localhost:8000/api/v1/predict -H "content-type: application/json" -d "{\"region_id\":\"mumbai\",\"lead_days\":1}"
```

If `weather_data` is `stale`, refresh the pipeline output: `uv run heatwave-ingest forecast && uv run heatwave-prepare sample`.

The database (`data/local/heatwave.db`) is created and migrated automatically on first start. To inspect or back it up:

```sh
uv run heatwave-db status       # migration version, pending migrations, row counts
uv run heatwave-db backup       # consistent copy into data/local/backups/
```

To start from an empty database, stop the API and delete `data/local/heatwave.db*`. Details: [database/README.md](database/README.md).

## 6a. Start MongoDB (Revision 2)

Pick one. Both give MongoDB 7.0 on `127.0.0.1:27017`.

```sh
# Container (Docker Desktop running). The named volume keeps data across restarts.
docker run -d --name heatwave-mongo -p 127.0.0.1:27017:27017 -v heatwave-mongo:/data/db mongo:7.0
docker start heatwave-mongo            # later sessions

# Native install
brew tap mongodb/brew && brew install mongodb-community@7.0 && brew services start mongodb-community@7.0   # macOS
# Windows: MongoDB Community Server 7.0 MSI from mongodb.com, installed "as a service"
# Linux: the mongodb-org 7.0 packages for your distribution, then: sudo systemctl start mongod
```

Then check it from the server workspace. The check is read-only:

```sh
cd server && npm run db:check
# MongoDB reachable at mongodb://127.0.0.1:27017/heatwave_local
#   server version : 7.0.x
#   database       : heatwave_local (0 collections)
```

The project uses its **own database, `heatwave_local`**, set in the `MONGODB_URI` path. If your MongoDB already holds other projects' databases, they are never touched. MongoDB creates `heatwave_local` only when something is first written to it (from Revision 2 step 4).

## 6b. Start the Node.js API (Revision 2)

```sh
cd server && npm run dev        # http://localhost:4000, restarts on change
```

Check it: http://localhost:4000/health returns `{"status":"ok","env":"local"}`, and http://localhost:4000/api/v1/health/ready returns `ready: true, database: "ok"`, or a 503 with `database: "unavailable"` while MongoDB is down. The API still starts without MongoDB and becomes ready as soon as it can connect. Since Revision 2 step 4 it serves places, weather and predictions from MongoDB and needs the ML service: run a **second** FastAPI process in ML role on port 8000, with the same token as `server/.env`:

```sh
SERVICE_ROLE=ml ML_SERVICE_TOKEN=<token> uv run uvicorn heatwave_api.main:app --port 8000
cd server && npm run score-all      # seed: score all 18 places x lead 0-3 (about 1 s)
```

Since step 5 **the frontend calls the Node.js API** (`VITE_API_BASE_URL=http://localhost:4000`) and every page needs a login. Locally a demo official is seeded (`official` / `demo-official-local`, from `server/.env`). Real accounts are issued with the CLI; there is no self-registration:

```sh
printf '%s' "$NEW_PASSWORD" | npm run users -- create asha --name "Asha Patil"   # password on stdin, at least 12 chars
npm run users -- list        # also: reset-password <u> (stdin), disable <u>, enable <u>
``` Details: [server/README.md](../server/README.md).

## 7. Start the frontend

```sh
cd frontend && npm run dev      # expected at http://localhost:5173 (strictPort, matches the backend's CORS default)
```

http://localhost:5173/design-system shows every design token and shared component (Part 10). Sign in from the account menu with `DEMO_USER_USERNAME` / `DEMO_USER_PASSWORD`. Details: [frontend/README.md](../frontend/README.md).

## 8. Verify end-to-end

Open http://localhost:5173. The nav's region selector should list the regions in `config/regions.yaml`, the footer should show the production model version, and the browser console should show no CORS errors. Once Part 11 lands, the dashboard shows the stored predictions for each region.

## Quality checks (run before pushing)

```sh
uv run pre-commit run --all-files
uv run pytest
(cd frontend && npm test)
(cd server && npm run typecheck && npm test)   # uses an in-memory MongoDB, not yours
```

## Troubleshooting

- **`uv` picks the wrong Python:** run `uv python install 3.13`, then `uv sync --all-packages` again.
- **Pre-commit frontend hooks fail with "eslint not found":** run `npm ci` inside `frontend/`.
- **OneDrive-synced checkout is slow or locks files:** clone outside OneDrive, or exclude `.venv/` and `node_modules/` from sync.
- **macOS: `XGBoost Library (libxgboost.dylib) could not be loaded` / `libomp.dylib` not found:** XGBoost needs the OpenMP runtime. Run `brew install libomp`. Without Homebrew access, point the loader at the copy that scikit-learn ships: `export DYLD_FALLBACK_LIBRARY_PATH="$PWD/.venv/lib/python3.13/site-packages/sklearn/.dylibs"`. Every Python test fails at import until one of these is done.
- **`heatwave-registry verify` says "No bundle with SHA-256 …" after `heatwave-train run`:** training is bit-for-bit reproducible only on the same platform. On Apple Silicon (checked 2026-10-20) the same pinned libraries choose the same hyperparameters but produce a slightly different XGBoost model (a different SHA-256 and prediction fingerprint), so the committed production pointer cannot be satisfied. Either copy the original `ml/artifacts/runs/20260928T100821Z-0bde51/` from a machine that has it, or, for local work only, evaluate, promote and explain your own run into a scratch registry (`MODEL_REGISTRY_DIR=/some/tmp/registry`). Never promote a local run into the committed `ml/registry/` by accident.
- **`backend/tests/test_production_model.py` errors with "No bundle with SHA-256 …" instead of skipping:** those tests skip only when `ml/artifacts/runs/` does not exist. Once any local run exists there (for example the Apple Silicon run above), they run against the committed pointer and fail. Either restore the original bundle, or move the local run out of `ml/artifacts/runs/` (and point `MODEL_ARTIFACT_DIR` at its new location when you use it).
- **`server` tests hang at the start or fail to download MongoDB:** the first `npm test` downloads a MongoDB 7.0.14 binary (about 70 MB) for the in-memory test database into `~/.cache/mongodb-binaries`. Offline, set `MONGOMS_SYSTEM_BINARY` to a local `mongod` 7.0 (for example `/opt/homebrew/bin/mongod`).
- **`npm run db:check` says "NOT reachable":** MongoDB is not running or not on `127.0.0.1:27017` (step 6a). An existing MongoDB 7.0 that already serves other projects is fine to reuse, because the project only uses its own `heatwave_local` database.

## Validation log

| Date | Who | OS | Steps passed | Notes |
|------|-----|----|--------------|-------|
| 2026-09-28 | Author (setup) | Windows 11 | 1–6 | Initial skeleton |
| 2026-09-28 | Claude Code (automated dry run, **not** a second person) | Windows 11 | 1–4, 6 | Clean export of the staged tree (`git checkout-index`) into an empty directory. `uv sync`, `npm ci`, env copies, `pytest` and `/health` all passed from scratch in about 16 s with warm caches. The pre-commit secret hook blocked a planted fake AWS key (exit 1). |
| 2026-10-20 | Claude Code (automated, **not** a second person) | macOS (Apple Silicon), Node 24 | 6–8 (5 partly) | No `uv` on PATH (used `.venv/bin`), so step 2 was not re-run. XGBoost needed the `libomp` workaround (Troubleshooting). `heatwave-train run` could not reproduce the committed production bundle on this platform, so the backend ran on a local run promoted into a scratch registry, with a scratch DB. The frontend dev server, region list, sign-in, `/design-system` and CORS all worked against it. Node 24 instead of the pinned 22 caused no failures. |
| 2026-10-20 | Claude Code (automated, **not** a second person) | macOS (Apple Silicon), Node 24, Homebrew MongoDB 7.0.31 | 3 (`server`), 6a (native install), 6b | Revision 2 step 1. `npm install` in `server/`, `db:check` against the running Homebrew MongoDB (read-only; existing databases unchanged), `npm start` → `/health` 200, readiness 200 with `database: "ok"`, NOT_FOUND envelope with an echoed request id, clean SIGTERM shutdown. The container path (Docker Desktop installed but not running) was not exercised. |
| | *second contributor* | | | **Required before Part 01 is "done"** |
