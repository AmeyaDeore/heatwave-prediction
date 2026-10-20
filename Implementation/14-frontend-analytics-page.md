# Part 14 — Frontend: Analytics (Trends & Insights) Page

**Depends on:** 10 (frontend architecture/design system), 07 (`GET /api/analytics`), 08 (historical data availability)
**Feeds into:** 16 (integration)
**Owner persona:** Frontend engineer

> **Revision 2 (2026-10-20, examiner feedback, M3):** the page becomes a real analysis feature for **places across Maharashtra**: 34 years of observed IMD weather history, heatwave patterns (frequency, trend, season, spells, extremes), stored predictions and forecast stability, with place comparison, side-by-side comparison of up to four places and a map view, all from MongoDB. The filters are **our proposal**, built from data the project already has. The examiner did not specify filters. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

## 1. Objective

Implement the "Analytics — Trends & Insights" screen — the historical and model-performance reporting view, matching the UI mockup's four-panel layout.

## 2. Page contents, section by section

### 2.1 Page header
- Title: "Analytics," subtitle: "Historical trends and model performance," current region.

### 2.2 Temperature Trend panel
- A line chart of temperature over a recent period (the mockup shows a week, Mon–Sun) for the selected region, with a clear visual threshold marking where readings cross into heatwave territory (the mockup's line changes from a normal color to a warning/red color partway through) — implement this threshold-crossing visual treatment deliberately using the risk color semantics from Part 10, not just a flat single-color line.
- Data sourced from `weather_snapshots` (Part 08) for the selected region and period, via `GET /api/analytics`.

### 2.3 Risk Distribution panel
- A breakdown (the mockup implies a stacked/segmented bar or similar) of the proportion of time/predictions falling into each risk class (Normal/Heatwave/Severe Heatwave) with percentages, color-coded per Part 10's semantics, for the selected region and period.
- Sourced by aggregating the `predictions` table (Part 08) over the selected period — confirm this aggregation query is efficient given the region+timestamp index defined in Part 08.

### 2.4 Heatwave Events panel
- A bar chart of heatwave event counts per month (the mockup shows Apr–Sep with varying bar heights/colors by severity), giving a seasonal view of how often elevated risk occurred.
- Define precisely what counts as one "event" (e.g., one calendar day where the prediction for that region was Heatwave or Severe Heatwave — document this counting rule explicitly, since it directly affects what the chart shows and must be consistent with how Part 03's classification rule defines the classes in the first place).

### 2.5 Model Performance panel
- Displays Precision, Recall, F1 Score, and Confidence for the currently deployed production model — sourced from Part 08's `model_metadata` table (populated from Part 05's evaluation report), not recomputed live. Include a note/tag indicating these metrics reflect the deployed model version, with the version identifier visible (even if small/secondary), so it's traceable back to Part 05's documentation if questioned.

## 3. Interaction behavior

- Provide a period selector (e.g., week/month/season) affecting the Temperature Trend and Risk Distribution panels — the mockup shows a week view by default; define what other periods are supported and how the query/aggregation changes accordingly.
- Region switching (global selector, Part 10) refreshes all panels except possibly the Model Performance panel, which is model-wide rather than region-specific — confirm and document this distinction explicitly, since it's a subtle but important difference from the other three panels.

## 4. Non-functional requirements

- Historical aggregation queries (trend, distribution, monthly event counts) must be efficient even as the `predictions`/`weather_snapshots` tables grow over time — confirm indexing from Part 08 supports the specific query patterns this page needs, and flag back to Part 08's owner if not.
- Charts must remain legible and color-consistent with the rest of the application — reuse Part 10's color tokens rather than a charting library's default palette.

## 5. Acceptance criteria / "done"

- [ ] All four panels implemented matching the mockup layout.
- [ ] "Heatwave event" counting rule documented and consistently applied.
- [ ] Period selector implemented and correctly re-queries the affected panels.
- [ ] Model Performance panel correctly sourced from deployed-model metadata, not recomputed client-side.
- [ ] Region-switch behavior correctly scoped (affects region-specific panels only).

## 6. Handoff note template

> Analytics page implemented at route: <path>. Event-counting rule: <definition>. Supported periods: <list>. Confirmed Model Performance panel reflects model version: <id>.

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **Built (minimal)** (scope freeze, uncommitted): observed history imported from Python (IMD 2000–2024, 164,376 place-days, 18 places), heatwave days per year with trend, seasonal pattern, records (hottest day, longest spell, largest departure), stored-prediction counts, the place comparison (with `?compare=`), shared-IMD-cell disclosure, model metrics. Not built: forecast stability (A7), the comparison map view, the period filters; the observed span is 2000–2024 (not 1991) because the export joins NASA POWER context.

**Why:** M3 asks for real data analysis of heatwave conditions for places within Maharashtra, with place selection. The owner's clarification: it must analyse **weather history, heatwave patterns and predictions** across the selected places, and let users **explore and compare places**. A map with markers is not enough. The examiner did not specify filters, so **every filter below is our proposal**, chosen because the data to back it already exists. None is presented as examiner-mandated.

### R2.1 Data the analysis uses (existing project data, no new sources)
| Dataset | Content | Origin | In MongoDB |
|---|---|---|---|
| **Observed history** | Daily IMD Tmax 1991–2024 per place, with normal, departure and the `IMD-HW-DAILY-v1` class, plus NASA POWER humidity, wind, solar and rain | Part 02 pulls; labelled **in Python** and exported (Part 03 R2.3) | `weather_snapshots` with `source: observed` |
| **Forecasts** | Open-Meteo today + 3 days per place, as fetched by each refresh | Part 02 R2.3b | `weather_snapshots` with `source: forecast` |
| **Predictions** | Every stored prediction: class, probabilities, factors, model version, lead | Node API (Part 07 §B), refreshed every 6 h | `predictions` |
| **Model metrics** | Deployed model, overall and per zone | ML service → `model_metadata` | `model_metadata` |

Observed history and model predictions are **never mixed in one series**. Every panel states which it shows, and the UI labels them "Observed (IMD)" and "Predicted (model)".

### R2.2 Analyses (each a panel, each answering a question an official asks)
| # | Panel | Question it answers | Data | Shown as |
|---|---|---|---|---|
| A1 | **Heatwave days per year** | Is heat getting more frequent here? | observed | bars per year (HEATWAVE and SEVERE stacked) 1991–2024, with a least-squares trend in days per decade, written out in words |
| A2 | **Seasonal pattern** | When in the year is this place at risk? | observed | month-by-month: share of heatwave days, mean Tmax vs normal |
| A3 | **Spells and extremes** | How long and how hot do episodes get? | observed | longest run of consecutive heatwave days, the 10 hottest days, the highest departure, per place |
| A4 | **Temperature trend** (§2.2, kept) | What happened over the selected period? | observed + forecast | daily Tmax with the normal and **the place's zone threshold** (37 °C coastal / 40 °C plains), with the line coloured where the threshold is crossed (§2.2's deliberate treatment) |
| A5 | **Risk distribution** (§2.3, kept) | How often is risk predicted here? | predictions | class shares over the period, per lead |
| A6 | **Heatwave events per month** (§2.4, kept) | How many events per month? | observed or predictions (toggle) | bars per month, using the documented counting rule (R2.4) |
| A7 | **Forecast stability** | Do forecasts for the same day change as it approaches? | predictions | for each valid date, the class at lead 3 → 2 → 1 → 0. It shows how settled a warning is before issuing it |
| A8 | **Place comparison** | Which places are most exposed? | observed (default) or predictions | sortable table, one row per place: heatwave days per year (mean), trend per decade, peak month, longest spell, record Tmax, latest predicted risk. A map view of the same column through `MaharashtraMap` district fill / sequential scale |
| A9 | **Compare places side by side** | How do two to four chosen places differ? | observed + predictions | A1, A2 and A5 for up to 4 places on shared axes, colours from the chart series tokens |
| A10 | **Model performance** (§2.5, kept) | How good is the model, and where? | `model_metadata` | precision, recall, F1, confidence, **per zone** after Part 05 R2, with the version id. Model-wide, never filtered by place |

**Honesty rules:** places that share an IMD 1° cell (Part 02 R2.3a), such as the Mumbai areas, are marked "same observed series as X" in A1–A3 and A8, so near-identical rows are not read as independent evidence. Predictions from the pre-retrain model at an inland place carry the Part 11 R2 caveat until Part 05 R2 promotes the v2 model.

### R2.3 Proposed filters (ours)
| Filter | Values | Applies to | Basis |
|---|---|---|---|
| Place | any place (the global selector) | A1–A7, A10 context | existing global region state |
| Compare set | up to 4 places | A9 | URL-encoded, so a comparison can be shared |
| Division | All / the six divisions | A8 | `division` in `regions.yaml` |
| Period | season (Mar–Jun) / year / 1991–2024 / last 7 or 30 days | A1–A6, A8 | §3's selector, made concrete; observed history spans 1991–2024, predictions only exist since scoring started |
| Data | Observed / Predicted | A6, A8 | R2.1 |
| Lead day | Today / +1 / +2 / +3 | A5, A7, A8 latest risk | the 1–3-day horizon |

### R2.4 Definitions to document in this part
- **Heatwave day:** a place-day whose class is HEATWAVE or SEVERE_HEATWAVE under `IMD-HW-DAILY-v1` (observed), or whose stored prediction for that valid date and lead is (predicted; the newest prediction per place, day and lead counts).
- **Event (A6, §2.4 owed):** a maximal run of consecutive heatwave days at one place; its severity is the highest class in the run. Single days count as an event. A duration rule, as IMD declares heatwaves over two days, is shown as an option, not the default.
- **Spell (A3):** the same run definition; its length in days.
- **Trend (A1):** an ordinary least-squares slope of annual heatwave days over the selected years, shown with the number of years used. With fewer than 10 years it is not shown.

### R2.5 How users reach it
- Analytics nav item (as before), defaulting to the selected place.
- From the dashboard (Part 11 R2): "Analyse" on a selected place opens A1–A7 for it, and "Compare" on the table opens A9 with the chosen rows.
- From the map: selecting a place in the A8 map view selects that place for A1–A7.

### R2.6 Serving
`GET /analytics` (Part 07 §B) returns the panels' series from MongoDB aggregations on the Part 08 R2 indexes. Observed-history aggregates per place and year are **precomputed at import** into a small summary collection, because 34 years × 18 places is about 225,000 rows and A8 should not scan them per request. Prediction aggregates are computed per request. Nothing is computed in the browser beyond formatting.

### R2 acceptance criteria
- [ ] Observed history 1991–2024 imported for every place from the Python export, with rule version and normals hash recorded; observed and predicted series kept apart in data and UI.
- [ ] Panels A1–A10 implemented; A4–A6 and A10 meet their original §2 criteria.
- [ ] Definitions in R2.4 documented and applied identically to observed and predicted data (unit-tested on a fixed fixture).
- [ ] Filters in R2.3 implemented, labelled as our proposal in the docs, each re-querying only the panels it affects.
- [ ] Shared-IMD-cell disclosure and the pre-retrain caveat shown where they apply.
- [ ] Entry points from the dashboard (Analyse, Compare) and the map work, and comparisons are shareable by URL.
- [ ] A8 and A9 answer from precomputed summaries in under 300 ms (query plan asserted); figures for one place match a hand-run aggregation of the export.
