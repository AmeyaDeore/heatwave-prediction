# Part 02 — Data Collection Pipeline

**Depends on:** 01 (environment/repo)
**Feeds into:** 03 (preprocessing/feature engineering)
**Owner persona:** ML/data engineer

## 1. Objective

Build the ingestion layer that acquires meteorological data from the three source types named in the project brief — IMD (India Meteorological Department), NASA POWER, and a historical/synthetic dataset — and lands it in a consistent, raw, queryable form for the preprocessing stage to consume.

## 2. Data sources to plan for

### 2.1 IMD (India Meteorological Department) temperature data
- Treat this as the authoritative source for maximum temperature and seasonal normal temperature for Indian locations, since the project's example region is Mumbai/Maharashtra.
- Plan for the reality that IMD does not expose a single simple public REST API for all needed fields — the plan must include a fallback path (manual/bulk download of published station data, or a licensed data provider) in case a live API is unavailable, rather than assuming programmatic access will just work.
- Document exactly which fields are sourced from IMD: maximum temperature, seasonal normal temperature (used to compute temperature deviation downstream).

### 2.2 NASA POWER
- Use as the source for the remaining meteorological variables named in the brief: relative humidity, wind speed, solar radiation, precipitation.
- NASA POWER is a genuine public API keyed by latitude/longitude and date range — plan the ingestion around: a fixed set of target locations (regions the system monitors, e.g., Mumbai, Kurla, Andheri, Dharavi, Colaba as seen in the dashboard mockups), a defined historical date range for training data, and a rolling recent-date window for live/forecast inference.
- Plan for API rate limits and transient failures: retries with backoff, and a local cache of already-fetched date ranges so re-runs don't re-download unchanged history.

### 2.3 Forecast weather data
- A separate near-term forecast feed is required for the "next 1–3 days" prediction window (this is distinct from historical data — historical data trains the model, forecast data feeds live inference).
- Decide and document the forecast source now (could be a forecast-specific NASA POWER product, a separate public forecast API, or, for the mini-project, a simulated/derived forecast) since Part 04's inference path depends on this being defined.

### 2.4 Historical/synthetic dataset
- The implementation slide states the working dataset is **5,000 synthetic records generated using simulated IMD heatwave criteria**. Treat this as the primary dataset for model training in the mini-project scope, with live IMD/NASA POWER ingestion as the path to real data for production use.
- The synthetic generation logic itself belongs in Part 03 (feature engineering), but this part owns the raw output format it lands in.

## 3. Ingestion pipeline design

Describe this as a sequence of stages, each with a clear input/output, regardless of which language/framework implements it:

1. **Source adapters** — one adapter per source (IMD, NASA POWER, forecast feed, synthetic generator), each responsible only for talking to its source and returning data in that source's native shape. Adapters should not do any cleaning or transformation — that belongs to Part 03.
2. **Raw landing zone** — every adapter writes its output to a raw storage area, partitioned by source and date/location, in an immutable, append-only fashion (never overwrite raw data — if a re-fetch is needed, land it as a new versioned file).
3. **Ingestion metadata log** — for every ingestion run, record: source, time range/locations requested, record count returned, any errors/gaps, and timestamp of the run. This is essential for debugging "why does the model look wrong" issues later.
4. **Scheduling** — decide the cadence per source: historical/training data is a one-time (or occasional) bulk pull; forecast data for live inference needs a recurring pull (e.g., a scheduled job) frequent enough to keep the "next 1–3 days" prediction current.

## 4. Fields to guarantee at the end of this stage

Regardless of source, the raw landing zone must be able to produce, per location and date, enough information to compute all of the input variables named in the brief:
- Maximum temperature
- Seasonal normal temperature
- Relative humidity
- Wind speed
- Solar radiation
- Precipitation
- Forecast weather data (for the live/inference path specifically)

If any source cannot supply a field, document that gap explicitly now rather than discovering it during Part 03 — it determines whether that field has to come from the synthetic dataset only, or needs an alternate source.

## 5. Data quality expectations to check for at ingestion time (not full cleaning — that's Part 03)

- Missing/null records per location/date.
- Obviously invalid values (e.g., impossible temperature or humidity readings) flagged but not silently dropped — log them for the preprocessing stage to handle deliberately.
- Duplicate records for the same location/date from a re-run.
- Gaps in date coverage per location (important for seasonal-normal calculations, which need enough historical depth).

## 6. Error handling & resilience

- Every source adapter must distinguish between "source is temporarily unavailable" (retry) and "source returned no data for this query" (not an error, just an empty result — log and continue).
- A partial failure (e.g., NASA POWER succeeds but IMD fails for one run) must not silently produce an incomplete training set — the ingestion metadata log (Section 3.3) should make this visible.
- Define a maximum retry policy and a clear failure state that surfaces to whoever is operating the pipeline.

## 7. Non-functional requirements

- Ingestion for a full historical pull (for initial model training) should be resumable — if it fails halfway, it should not need to restart from zero.
- Location list (regions monitored) should be a configuration value, not hard-coded, since the dashboard already anticipates multiple regions (Mumbai, Kurla, Andheri, Dharavi, Colaba).
- Raw data storage format should be chosen for easy downstream reading by the preprocessing stage (e.g., a columnar or simple tabular file format) and should not require the preprocessing stage to know anything about the original source's API shape.

## 8. Acceptance criteria / "done"

- [x] Source adapters defined (even as stubs/mocks initially) for IMD, NASA POWER, forecast feed, and synthetic generator, each with a documented input/output contract. *(All four are real, not stubs: `ml/src/heatwave_ml/ingestion/adapters/`. Contracts are in `docs/data/raw-landing-zone.md`.)*
- [x] Raw landing zone structure defined and populated with at least one successful run per source. *(2026-09-28: IMD 2023 via HTTP, NASA POWER 2000–2024 × 5 regions = 45,660 rows, Open-Meteo 5 regions × 4 days, synthetic 5,000 rows.)*
- [x] Ingestion metadata log implemented and demonstrably capturing at least one success and one deliberately-forced failure. *(`data/raw/_meta/ingestion_log.jsonl`. Forced failure: run `20260928T083203.722563Z-0c0e3e`, NASA POWER pointed at a closed port, status `failed`, exit code 2. See `heatwave-ingest status`.)*
- [x] Field-availability gap analysis (Section 4) written down and shared with whoever owns Part 03. *(`docs/data/field-availability.md`, which includes the handoff note. **Share it with the Part 03 owner.**)*
- [x] Location list is externalized as configuration. *(`config/regions.yaml` via `MONITORED_REGIONS_FILE`.)*
- [x] A scheduled/recurring pull path exists (even if manually triggered for the mini-project) for the forecast feed specifically. *(`uv run heatwave-ingest forecast`, with Task Scheduler/cron entries in `docs/data/raw-landing-zone.md#scheduling`.)*

**Also verified:** resumable historical pull (a re-run skipped all 125 landed chunks in 1.5 s). Immutable landing (a forced re-fetch adds a version and never overwrites). Retry versus permanent-error classification. Partial-failure status. 25 automated tests in `ml/tests/test_ingestion_*.py`.

## 9. Handoff note template

> Raw data available at: <location/path pattern>. Sources implemented: <list>. Known field gaps: <list>. Location list config lives at: <path>. Part 03 can now build preprocessing against this raw shape.

**Filled in:** see §4 of [`docs/data/field-availability.md`](../docs/data/field-availability.md).
