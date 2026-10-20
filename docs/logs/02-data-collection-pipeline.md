# Log 02 — Data collection pipeline

| | |
|---|---|
| Plan | [Implementation/02-data-collection-pipeline.md](../../Implementation/02-data-collection-pipeline.md) |
| Status | Complete |
| Date | 2026-09-28 |
| Branch / commits | `main` · `39df378` feat(ingestion): implement weather data collection pipeline and landing zone |
| Tests | 23 new (`ml/tests/test_ingestion_*.py`), 25 total |

## Summary

Built the ingestion layer: four real source adapters (IMD, NASA POWER, Open-Meteo forecast, synthetic), an immutable raw landing zone, an append-only run log, retry/backoff handling, and the `heatwave-ingest` CLI. Real data was pulled for every source, and a field-availability gap analysis was handed to Part 03.

## What was built

**Package `ml/src/heatwave_ml/ingestion/`**

| Module | Role |
|---|---|
| `adapters/base.py` | Adapter contract: chunk (region + date window) → `FetchResult` (native bytes + flattened frame) |
| `adapters/imd.py` | IMD gridded daily Tmax, 1°×1° binary `.GRD` per year (float32 31×31×days). HTTP POST to the IMD Pune form, **plus a manual inbox fallback** (`IMD_INBOX_DIR`) |
| `adapters/nasa_power.py` | NASA POWER daily point API (`community=AG`): historical whole years, and a rolling recent window |
| `adapters/open_meteo.py` | Open-Meteo forecast for the next `FORECAST_DAYS` (inference only, never training) |
| `adapters/synthetic.py` | Lands a synthetic batch through the same path (Part 03 plugs in the real generator) |
| `http.py` | `HttpClient` + `RetryPolicy`: exponential backoff 2 s·2ⁿ capped at 60 s, honours `Retry-After`; retryable (network, 408/425/429/5xx) vs permanent errors |
| `landing.py` | `RawLandingZone`: immutable, one file per chunk per run, Parquet (canonical columns) **plus** the verbatim native payload; re-fetch adds a version, never overwrites |
| `quality.py` | Per-chunk quality report (counts only; nothing dropped at this stage) |
| `runlog.py` | Append-only, fsync-per-line JSONL log (`data/raw/_meta/ingestion_log.jsonl`); later reused by the Part 04 experiment log and Part 05 registry history |
| `pipeline.py` | Orchestration: resume (skip landed chunks), failure isolation per chunk, overall run status |
| `regions.py`, `settings.py` | Region list from `config/regions.yaml`; env-driven settings |
| `cli.py` | `heatwave-ingest historical / recent / forecast / synthetic / status` |

**Data landed (2026-09-28):** IMD 2023 via HTTP; NASA POWER 2000–2024 × 5 regions = 45,660 rows; Open-Meteo 5 regions × 4 days; synthetic 5,000 rows.

**Docs:** `docs/data/raw-landing-zone.md` (stages, adapter contracts, error handling, layout, tabular schema, scheduling), `docs/data/field-availability.md` (which source supplies which field, gaps, handoff), ADR `docs/decisions/0002-data-sources.md`.

## Key decisions and why

- **IMD for Tmax and the seasonal-normal history:** the authoritative Indian source, and the only bulk-downloadable official daily product. IMD has no REST API, and its host was unreliable on the day (TLS failures), hence the inbox fallback.
- **NASA POWER for humidity, wind, solar radiation and precipitation:** public, keyless, daily since 1981; `AG` gives solar in MJ/m²/day.
- **Open-Meteo for the 1–3 day forecast:** NASA POWER has no forecast product and IMD has no machine-readable district forecast.
- **Parquet + native payload, immutable:** Part 03 reads one tabular shape, and the raw bytes remain for audit and re-parsing.
- No source needs an API key, so there are no weather-data secrets.

## Verification

- A forced failure was captured in the log: run `20260928T083203.722563Z-0c0e3e` pointed NASA POWER at a closed port, status `failed`, exit code 2.
- A resumable re-run skipped all 125 landed chunks in 1.5 s.
- A forced re-fetch added a new version instead of overwriting (`chunks_with_multiple_versions=1` in `status`).
- Retry vs permanent-error classification and partial-failure status are covered by the 23 tests.

## Deviations from the plan and issues found

- The test count was first misstated as 25 in the plan checklist; corrected to 23 when re-checked before Part 03.
- The adapters are real implementations, not the stubs the plan allowed.

**Field gaps handed to Part 03** (`field-availability.md` §2): the seasonal normal must be derived, not downloaded; Tmax sources must not be mixed inside the deviation feature; the 5 sub-city regions fall into only two IMD cells (not distinguishable in real history); wind height differs (NASA 2 m vs Open-Meteo 10 m); recent observations lag 2–4 days; real heatwave days are rare at the coastal threshold; IMD availability is unreliable.

## Open items / follow-ups

- IMD station CSVs (licensed) are worth revisiting for production.
- The recurring forecast pull is manual (`heatwave-ingest forecast`); Task Scheduler/cron entries are documented, not installed.

## Handoff

Raw data at `data/raw/<source>/<chunk key>/<run_id>.parquet`, read with `RawLandingZone(...).read_latest(source)`. The region list is `config/regions.yaml`. Part 03 can build preprocessing against this raw shape.

## Update 2026-10-20: Revision 2 step 2, region hierarchy fields

`heatwave_ml.ingestion.regions.Region` gains the optional `division`, `kind` (default `city`) and `parent`, plus `validate_hierarchy`: the kind must be `city` or `area`, an area must name a city in the same file, and a city cannot have a parent. Unknown keys still raise `TypeError`, so a typo such as `divison` cannot be silently ignored. The FastAPI catalog reuses the same function, so ingestion and the API cannot disagree. `config/regions.yaml` is **unchanged**: the Maharashtra places land in step 3, together with their normals. Tests: 8 new in `ml/tests/test_ingestion_adapters.py`, and all existing ingestion tests pass.

## Update 2026-10-20: Revision 2 step 3, Maharashtra places and real data pulls

- **Places:** `config/regions.yaml` now lists **our proposed selection** of 18 Maharashtra places (14 cities across the six divisions + the 4 Mumbai areas, which become `kind: area, parent: mumbai`). It is labelled in the file and in `config/README.md` as the project's selection, not an examiner-specified list. The original five entries are value-identical (checked programmatically).
- **Pulls (live, 2026-10-20, this Mac):** IMD gridded Tmax 34/34 years 1991–2024 (223,542 rows, ~35 s: one all-India file per year, so 18 places cost the same as 5); NASA POWER 450/450 place-years 2000–2024 (164,376 rows; one connection reset retried automatically); Open-Meteo forecast 18/18 places (72 rows). **0 nulls** in either history. Nothing was synthesised or filled in.
- **IMD cells:** 18 places → 13 distinct series (shared: Andheri/Dharavi/Kurla/Thane; Mumbai/Colaba; Akola/Amravati). Recorded in `docs/data/field-availability.md` §5 for the analysis disclosure.
- `data/sample/forecast_features.csv` (committed) is regenerated through the inference path for all 18 places, issued 2026-10-20, so readiness reports `weather_data: ok` instead of `stale`.
- **Not done:** the 6-hourly scheduled refresh (step 6). Until then the sample ages and is again flagged stale after 36 h.
