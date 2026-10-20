# Part 02 — Data Collection Pipeline

**Depends on:** 01 (environment/repo)
**Feeds into:** 03 (preprocessing/feature engineering)
**Owner persona:** ML/data engineer

> **Revision 2 (2026-10-20, examiner feedback):** monitoring extends from five Mumbai areas to places across Maharashtra, for the map (M4) and the analysis (M3). The adapters already take their location list from config, so this is a configuration and data-pull change, not new ingestion code. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

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

**Also verified:** resumable historical pull (a re-run skipped all 125 landed chunks in 1.5 s). Immutable landing (a forced re-fetch adds a version and never overwrites). Retry versus permanent-error classification. Partial-failure status. 23 automated tests in `ml/tests/test_ingestion_*.py`. *(Re-checked 2026-09-28 before Part 03: all pass. The count was previously misstated as 25. A forced re-fetch now also shows live in `status` as `chunks_with_multiple_versions=1` for `synthetic`.)*

## 9. Handoff note template

> Raw data available at: <location/path pattern>. Sources implemented: <list>. Known field gaps: <list>. Location list config lives at: <path>. Part 03 can now build preprocessing against this raw shape.

**Filled in:** see §4 of [`docs/data/field-availability.md`](../docs/data/field-availability.md).

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **In progress.** ✅ Step 2 (loaders) and ✅ step 3 (places and real data pulls) built, uncommitted. `config/regions.yaml` holds our proposed 18 places with real IMD, NASA POWER and forecast data landed and **no gaps**. ⏳ Not started: the 6-hourly refresh (step 6).

**Why:** the examiner asked for heatwave monitoring and analysis of places in Maharashtra, shown on a Maharashtra map. They did not give an exhaustive list of cities or filters. **The list below is our proposed initial selection, not the examiner's list.** It stays configurable in `config/regions.yaml`, and a place can be added or removed without code changes (subject to R2.3).

### R2.1 Proposed initial place set

Selection rule: at least one place in each of Maharashtra's six administrative divisions, favouring district headquarters with known pre-monsoon heat exposure (Vidarbha, Khandesh, Marathwada) while keeping the coastal Konkan. The five existing Mumbai areas are kept unchanged, because they are what the trained model, the tests and the mockups use.

| Division | Place (`id`) | District | Zone (labelling rule) | Approx. lat, lon | Status |
|---|---|---|---|---|---|
| Konkan | Mumbai (`mumbai`) + areas Kurla, Andheri, Dharavi, Colaba | Mumbai City / Suburban | coastal | existing | **existing** |
| Konkan | Thane (`thane`) | Thane | coastal | 19.218, 72.978 | proposed |
| Konkan | Ratnagiri (`ratnagiri`) | Ratnagiri | coastal | 16.990, 73.312 | proposed |
| Pune | Pune (`pune`) | Pune | plains | 18.520, 73.857 | proposed |
| Pune | Solapur (`solapur`) | Solapur | plains | 17.660, 75.906 | proposed |
| Pune | Kolhapur (`kolhapur`) | Kolhapur | plains | 16.705, 74.243 | proposed |
| Nashik | Nashik (`nashik`) | Nashik | plains | 19.998, 73.790 | proposed |
| Nashik | Jalgaon (`jalgaon`) | Jalgaon | plains | 21.008, 75.563 | proposed |
| Chhatrapati Sambhajinagar | Chhatrapati Sambhajinagar (`sambhajinagar`) | Chhatrapati Sambhajinagar | plains | 19.876, 75.343 | proposed |
| Chhatrapati Sambhajinagar | Nanded (`nanded`) | Nanded | plains | 19.138, 77.321 | proposed |
| Amravati | Amravati (`amravati`) | Amravati | plains | 20.937, 77.780 | proposed |
| Amravati | Akola (`akola`) | Akola | plains | 20.700, 77.008 | proposed |
| Nagpur | Nagpur (`nagpur`) | Nagpur | plains | 21.146, 79.088 | proposed |
| Nagpur | Chandrapur (`chandrapur`) | Chandrapur | plains | 19.962, 79.296 | proposed |

Coordinates are approximate city centroids. Part 02 verifies each against the IMD grid cell and NASA POWER point actually used, as it did for the original five. Zone assignment follows `docs/data/heatwave-labeling-spec.md` (coastal 37 °C, plains 40 °C). A hills place (for example Mahabaleshwar) can be added later the same way.

### R2.2 `regions.yaml` schema additions (backwards-compatible)
- `division`: one of the six divisions above. It drives grouping in the region selector, the map legend and the division filter (Part 14 R2).
- `kind`: `city` or `area`, with `parent` set for areas (`kurla.parent = mumbai`). The map shows areas only when zoomed into Mumbai, so 18 markers do not pile up on one city.
- Existing fields (`id`, `name`, `district`, `state`, `zone`, `lat`, `lon`) are unchanged.
- **Conflict with the existing code (must be fixed first):** both Python loaders build regions strictly from the YAML keys: `heatwave_ml.ingestion.regions.Region(**entry)` and `heatwave_api.catalog.RegionInfo(**r)`. An unknown key raises at import/startup, so adding `division`/`kind`/`parent` as written would **break ingestion and the FastAPI service**. Fix: add the three fields to both dataclasses as optional (`division`, `kind` default `city`, `parent` default none), keep rejecting truly unknown keys so typos still fail, and expose them from the FastAPI `GET /regions`. This is a small change to Part 02 and Part 07 code, with tests, and it lands **before** any place is added.

### R2.3 Data pulls for the new places (existing adapters, no new code)
- **IMD gridded Tmax history**, 1991–2020 at least, for every new place's grid cell. This is needed for its seasonal normals (Part 03 R2). It uses the existing resumable bulk pull.
- **NASA POWER 2000–2024** daily history per place: the training-era variables and the per-place climatology used by synthetic generator v2 (Part 03 R2), plus the historical weather that Part 14 R2's analysis imports.
- **Open-Meteo forecast** (today + 3 days) for every place in the existing scheduled pull, and `data/sample/forecast_features.csv` regenerated so the ML service can score every place.
- **Ordering rule:** a place is added to `regions.yaml` in the same change that lands its normals. The ML service builds features from the normals table and cannot score a place without one (master plan §4.1).

### R2.3a What "actual weather data" means per source (so the map and analysis are honest)
| Use | Source | Real? | Note |
|---|---|---|---|
| Map and dashboard, today + 3 days | Open-Meteo forecast (~0.1° grid) | **yes**, live forecast | distinct for every place, including the Mumbai areas |
| Weather-history analysis, 1991–2024 | IMD gridded Tmax (1°) | **yes**, observed | the same source as the normals, so the departure is never mixed-source (`field-availability.md` §2.2). At 1°, **the five Mumbai areas share two cells**, and nearby cities may share one (Mumbai and Thane, for example). The analysis must say when places share a cell (Part 14 R2) |
| Humidity, wind, solar and rain history | NASA POWER (~0.5°) | yes, observed | context only; never used for the temperature departure |
| Model training | synthetic `imd-sim-v2`, calibrated on the above | no, by design (the brief) | Part 03 R2 |

The landed history is git-ignored. On a new machine (including the current development Mac, where `data/raw/` is empty) it must be pulled again before normals or analysis can be built. The IMD host is unreliable (§2.7 of field-availability): pulls are resumable, and the manual-inbox fallback applies. Allow time for it.

### R2.3b Scheduled refresh (so the map shows current conditions)
Today the forecast file is the committed sample, issued 2026-09-28, and the shell flags it as stale. For the map to show actual current risk, the existing scheduled-pull path (§3 stage 4, cron / Task Scheduler entries in `docs/data/raw-landing-zone.md`) runs, every 6 hours: `heatwave-ingest forecast` → `heatwave-prepare sample`. The ML service reloads the file when its modification time changes (already built). Then the Node scoring CLI scores every place for lead 0–3 (Part 07 §B). This is the CLI from Part 11 R2 on a schedule, with no new scheduler technology. It is not scoring on page view, which was ruled out. If the job stops, data ages and is shown as stale, never presented as current.

### R2.4 Effect on the rest of the plan
- The field-availability analysis (`docs/data/field-availability.md`) gets a per-place row. Inland places are expected to have fewer gaps in solar and precipitation than the coastal monsoon cells, and any gap is recorded the same way.
- Ingestion volume grows from 5 to 18 points. The NASA POWER pull is about 3.6× the original 45,660 rows, still a single resumable run.

### R2 acceptance criteria
- [x] Both Python region loaders accept the optional `division`, `kind`, `parent` fields and still reject unknown keys; existing tests pass, plus new ones (lands first). *(2026-10-20: `heatwave_ml.ingestion.regions` adds the fields and `validate_hierarchy` (kind ∈ city/area; an area names a city in the same file; a city has no parent). The FastAPI catalog reuses the same function, and `GET /regions` exposes the fields. 8 new tests in `ml/tests/test_ingestion_adapters.py`, plus 2 in `backend/tests/test_ml_service_role.py`.)*
- [x] Proposed place set reviewed by the team and recorded in `config/regions.yaml` with `division`, `kind` and `parent`, and labelled in `config/README.md` as our proposal. *(Owner approved it as our provisional project scope on 2026-10-20: 14 cities across the six divisions + the 4 Mumbai areas, labelled in the file and in `config/README.md` as our selection, not examiner-mandated. The original five entries are value-identical.)*
- [x] Which places share an IMD 1° cell is computed and recorded in `docs/data/field-availability.md`, for the analysis disclosure. *(From the landed data: 18 places → 13 distinct series; shared cells: Andheri/Dharavi/Kurla/Thane, Mumbai/Colaba, Akola/Amravati. §5 of that file.)*
- [ ] The 6-hourly refresh (ingest → prepare sample → score all places) documented with cron and Task Scheduler entries, and run once end to end.
- [x] Coordinates verified per place (grid cell and point recorded in `docs/data/field-availability.md`). *(The IMD cell and its distance per place are recorded (35.6–63.4 km). NASA POWER and Open-Meteo use each place's own coordinates. The centroids are approximate city centres, as for the original five.)*
- [x] IMD history, NASA POWER history and forecast pulls landed for every new place, visible in `heatwave-ingest status`. *(2026-10-20, live sources: IMD 34/34 years 1991–2024 (223,542 rows), NASA POWER 450/450 chunks 2000–2024 (164,376 rows), Open-Meteo 18/18 places (72 rows); 0 nulls. Raw data is git-ignored, so another machine must re-pull (resumable, about 10 minutes here).)*
- [x] Field-availability gap analysis extended to the new places and shared with Part 03. *(`docs/data/field-availability.md` §5: no field gaps for any new place.)*
- [x] Ingestion tests still pass, plus one test that the new `regions.yaml` fields are accepted and ignored where unused. *(All existing ingestion tests pass; `test_regions_without_the_new_fields_still_load_with_defaults` and `test_division_kind_and_parent_are_read` cover both directions. The adapters use only id/lat/lon/zone, so they ignore the new fields.)*
