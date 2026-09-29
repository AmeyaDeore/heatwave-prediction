# Raw landing zone and ingestion pipeline (Part 02)

The contract between Part 02 (ingestion) and Part 03 (preprocessing). The code is in `ml/src/heatwave_ml/ingestion/`. Source choices are explained in [ADR 0002](../decisions/0002-data-sources.md).

## Running it

```sh
uv run heatwave-ingest historical --source nasa_power   # 2000-2024 x all regions, resumable
uv run heatwave-ingest historical --source imd          # IMD Tmax 1991-2024, resumable
uv run heatwave-ingest synthetic                        # 5,000-row synthetic batch
uv run heatwave-ingest recent                           # NASA POWER last 14 days (inference context)
uv run heatwave-ingest forecast                         # Open-Meteo next 3 days (schedule this)
uv run heatwave-ingest status                           # recent runs, failures, landed coverage
```

Options: `--regions mumbai,colaba` limits which regions are pulled. `--start/--end YYYY-MM-DD` (historical only) overrides the env date range. `--force` re-fetches chunks that are already landed.

**Exit codes:** `0` means success or empty, `1` means partial failure, `2` means every chunk failed. Anything non-zero needs an operator to look at `heatwave-ingest status`.

## Stages

| # | Stage | Input → Output | Module |
|---|-------|----------------|--------|
| 1 | Source adapter | chunk (region + date window) → `FetchResult` (native bytes + flattened frame) | `adapters/*.py` |
| 2 | Quality check | frame → report (counts only; nothing dropped) | `quality.py` |
| 3 | Raw landing | `FetchResult` → immutable files under `data/raw/` | `landing.py` |
| 4 | Metadata log | one event per run start, per chunk and per run finish → JSONL | `runlog.py` |
| 5 | Orchestration | adapter + chunk list → run summary. Handles resume, isolates failures, sets overall status | `pipeline.py` |
| 6 | Scheduling | cadence per source (below) | `cli.py` + OS scheduler |

## Adapter contracts

Each adapter talks **only** to its source. It flattens to one row per (region, date) and renames columns to the canonical names. It also decodes the source's documented "missing" sentinel to null (NASA POWER `-999`, IMD `99.9`). **Nothing else changes.** Units stay as reported (they already match; see below). No row is dropped, capped or imputed.

| Adapter (`source`) | Input | Chunk key (= landing path) | Native file | Resumable? |
|---|---|---|---|---|
| `imd` | year range; all regions | `year=<YYYY>` | `.native.grd` (float32 31×31×days) | past years yes; current year no |
| `nasa_power` historical | regions × date range | `region=<id>/year=<YYYY>` (whole calendar years) | `.native.json` | yes, once the year ended 30+ days ago (POWER back-fills) |
| `nasa_power` recent | regions, `NASA_POWER_RECENT_DAYS` | `region=<id>/recent=<today>` | `.native.json` | no, always fetched |
| `open_meteo_forecast` | regions, `FORECAST_DAYS` | `region=<id>/issued=<today>` | `.native.json` | no, always fetched |
| `synthetic` | regions, count, seed, date range, generator | `generator=<version>/seed=<n>-n=<count>` | (none: the frame is the output) | yes (deterministic) |

"Today" means the calendar day in India (IST).

### Failure semantics (every adapter)

| Situation | Raised / returned | Retried? | Chunk status in log |
|---|---|---|---|
| Network error, timeout, HTTP 408/425/429/5xx | `SourceUnavailable` after `INGEST_MAX_ATTEMPTS` | yes, exponential backoff `2s·2ⁿ` capped at 60s, honours `Retry-After` | `failed`, `retryable: true` |
| Other 4xx, wrong-size IMD file, unexpected JSON shape | `SourceRequestError` | no | `failed`, `retryable: false` |
| Source answered but had no data for the query | empty frame | – | `empty` (not an error) |
| Bug inside an adapter | any exception | no | `failed`; the other chunks keep going |

Run status is `success` (nothing failed), `partial` (some chunks failed), `failed` (all failed), `empty` (nothing failed, no data), or `incomplete` (the process died mid-run; no `run_finished` event). **A partial run never looks like a smaller dataset:** it is marked partial, exits with code 1, and `status` lists each failed chunk.

## Directory layout

```
data/raw/
├── _meta/ingestion_log.jsonl
├── imd/
│   ├── _inbox/                          # hand-downloaded Maxtemp_MaxT_<year>.GRD (IMD fallback)
│   └── year=2023/<run_id>.parquet + <run_id>.native.grd
├── nasa_power/region=mumbai/year=2023/<run_id>.parquet + .native.json
├── nasa_power/region=mumbai/recent=2026-09-28/...
├── open_meteo_forecast/region=mumbai/issued=2026-09-28/...
└── synthetic/generator=placeholder-v0/seed=42-n=5000/<run_id>.parquet
```

- `run_id` = `YYYYMMDDTHHMMSS.ffffffZ-<6 hex>`. It is UTC, and sorting it by name sorts by time.
- **Immutable:** files are created with exclusive-create and never rewritten. A re-fetch (`--force`, or a non-resumable chunk) adds a new `run_id` beside the old one. Parquet is written to a temp name and renamed, so a crash never leaves a half file that resume would mistake for landed data.
- **Duplicates from re-runs** therefore exist on disk as extra versions by design. Readers must use `read_latest`, which takes the newest version per chunk. `status` reports how many chunks have more than one version.

## Tabular schema (every parquet file)

| Column | Type | Sources | Notes |
|---|---|---|---|
| `region_id` | str | all | id from `config/regions.yaml` |
| `date` | datetime (midnight, tz-naive) | all | local calendar day (POWER uses local solar time, Open-Meteo `Asia/Kolkata`) |
| `tmax_c` | float, °C | all | |
| `normal_tmax_c` | float, °C | synthetic | real sources: Part 03 derives it from IMD history |
| `rh_pct` | float, % | nasa_power, open_meteo_forecast, synthetic | daily mean at 2 m |
| `wind_ms` | float, m/s | nasa_power, open_meteo_forecast, synthetic | **height differs**: see `wind_height_m` |
| `wind_height_m` | int | nasa_power (2), open_meteo_forecast (10) | |
| `solar_mj_m2` | float, MJ/m²/day | nasa_power, open_meteo_forecast, synthetic | |
| `precip_mm` | float, mm/day | nasa_power, open_meteo_forecast, synthetic | |
| `grid_lat`, `grid_lon` | float | imd, open_meteo_forecast | grid cell actually used |
| `grid_distance_km` | float | imd | region centroid → nearest IMD cell with data |
| `lead_days` | int | open_meteo_forecast | 0 = today, 1-3 = the prediction horizon |
| `issued_at` | ISO-8601 str (UTC) | open_meteo_forecast | when the forecast was fetched |
| `record_id` | int | synthetic | the unique key; (region, date) may repeat |
| `source`, `run_id` | str | all | provenance, added at landing |

Reading it from Part 03:

```python
from heatwave_ml.ingestion.landing import RawLandingZone
from heatwave_ml.ingestion.settings import IngestionSettings

zone = RawLandingZone(IngestionSettings.from_env().raw_data_dir)
nasa = zone.read_latest("nasa_power")  # adds a chunk_key column
```

## Ingestion metadata log

`data/raw/_meta/ingestion_log.jsonl` holds one JSON object per line:

- `run_started`: `run_id, source, job, request {regions, dates…}, chunk_count, started_at`
- `chunk`: `run_id, key, status, records, files, quality, notes, error, retryable, at`
- `run_finished`: `run_id, status, counts {status: n}, records, finished_at`

The `quality` report holds per-field null counts, out-of-bounds counts, duplicate keys, and date gaps per region (with the first missing dates). `notes` holds source provenance, for example IMD `origin` (`http` or `inbox:<file>`) with the grid cell and distance per region, and POWER's units and upstream products.

## Scheduling

| Source | Cadence | Why |
|---|---|---|
| `forecast` (Open-Meteo) | **every 6 hours** | Global models update every 6 hours. It keeps the "next 1–3 days" prediction current. |
| `recent` (NASA POWER) | daily | POWER has a few days' latency, so more often gains nothing |
| `historical` (IMD, NASA POWER) | once, then yearly (January) | A resumable bulk pull. Re-running only fetches missing or non-final chunks. |
| `synthetic` | on demand | Deterministic. Only re-run when the generator, seed or count changes. |

For the mini-project, the forecast pull is **manually triggerable** (`uv run heatwave-ingest forecast`) and can be registered with the OS scheduler.

Windows (Task Scheduler, every 6 h):

```powershell
schtasks /Create /TN "heatwave-forecast" /SC HOURLY /MO 6 /F `
  /TR "cmd /c cd /d C:\path\to\heatwave-prediction && uv run heatwave-ingest forecast >> data\local\forecast-cron.log 2>&1"
```

Linux/macOS (cron):

```cron
0 */6 * * *  cd /path/to/heatwave-prediction && uv run heatwave-ingest forecast >> data/local/forecast-cron.log 2>&1
15 6 * * *   cd /path/to/heatwave-prediction && uv run heatwave-ingest recent   >> data/local/recent-cron.log 2>&1
```

Part 18 moves these into the deployed scheduler, and alerts on non-zero exit codes.

## IMD manual fallback

If `historical --source imd` fails with `Download it by hand…`:

1. Open https://www.imdpune.gov.in/cmpg/Griddata/Max_1_Bin.html in a browser, pick the year, and download.
2. Save it as `data/raw/imd/_inbox/Maxtemp_MaxT_<year>.GRD`.
3. Re-run `uv run heatwave-ingest historical --source imd`. The inbox is checked first, and the log records `origin: inbox:<file>`.
