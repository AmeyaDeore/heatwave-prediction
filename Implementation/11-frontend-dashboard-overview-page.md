# Part 11 — Frontend: Dashboard Overview Page

**Depends on:** 10 (frontend architecture/design system), 07 (`GET /api/weather`, latest predictions)
**Feeds into:** 16 (integration)
**Owner persona:** Frontend engineer

> **Revision 2 (2026-10-20, examiner feedback, M4):** the "visual regional overview" in §2.3 becomes an **interactive Maharashtra map** of every monitored place, coloured by latest predicted risk. The page's other sections are unchanged. The open decisions in §3 and §4 are now settled. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

## 1. Objective

Implement the "Heatwave Command Center" — the landing screen giving a real-time summary of heatwave risk across all monitored regions, matching the UI mockup exactly.

## 2. Page contents, section by section

### 2.1 Page header
- Title: "Heatwave Command Center."
- Subtitle: "Climate intelligence for heatwave monitoring, prediction and early warning."
- "Last updated" timestamp, live from the most recent successful data fetch.

### 2.2 Top metric row (four metric cards, using the shared Metric Card component from Part 10)
1. **Current Temperature** — value with a delta sub-label (e.g., "+3.0° above seasonal normal") for the currently selected region.
2. **Heatwave Risk** — the current risk class (using the shared Risk Badge component) with its prediction-probability sub-label.
3. **Prediction Confidence** — the model's confidence percentage for the current prediction.
4. **Forecast** — the forecast window label ("Next 1–3 Days") with a short sub-label ("Elevated heat risk" or equivalent, derived from risk class).

All four cards source from the same latest-prediction API response for the selected region (Part 07's prediction data plus `GET /api/weather`) — avoid making four separate uncoordinated API calls for what is conceptually one snapshot.

### 2.3 Regional Heatwave Risk panel
- A visual regional overview (the mockup shows a bubble/scatter-style visualization sized or colored by risk) plus a table listing each monitored region (Kurla, Andheri, Dharavi, Colaba, etc.) with columns: Area, Temperature, Risk (using the Risk Badge component).
- This requires a "latest prediction per region" query — confirm with Part 08's schema/indexing (region + timestamp index) that this is efficient.
- Include the "DEMO DATA" tag component where the underlying data is not yet live-sourced, and a small note like "Areas requiring closer monitoring" for context.

### 2.4 "Why this prediction?" panel
- A condensed version of the SHAP explanation (full detail lives on the Prediction page, Part 12) — top 2–3 contributing factors with proportional bars, using the shared Contributing-Factor Bar component, labeled with the "AI EXPLAINED" tag.
- This panel should link/navigate to the full Prediction page for the same region for full detail, rather than duplicating all of Part 12's content here.

### 2.5 Recommended Authority Actions panel
- A short numbered list (using the shared Action List Item component) of recommended actions for the current risk level, labeled "ACT NOW," sourced from the same deterministic action-mapping defined in Part 07 Section 3.1.

## 3. Interaction behavior

- Changing the selected region (via the global nav shell selector from Part 10) refreshes every panel on this page against the newly selected region.
- The regional table's rows should be clickable/navigable, setting the selected region and/or navigating to the Prediction page for that region — define exactly which, since both are plausible UX and should be a deliberate choice, not an accident of implementation.
- Auto-refresh interval for this page's data, per Part 10 Section 3's polling convention (this is the page where live-feeling data matters most, being the "command center").

## 4. Non-functional requirements

- All four top metric cards and the regional table must load from the minimum necessary number of API calls (avoid a waterfall of many small requests) — if the backend contract from Part 07 doesn't support returning this composite view in one call, flag that back to Part 07 rather than working around it with many frontend calls.
- Page must degrade gracefully (per Part 10's loading/error/empty state conventions) if the prediction API is temporarily unavailable — showing stale-but-labeled data or a clear error state, never a blank/broken screen.

## 5. Acceptance criteria / "done"

- [ ] Page header, four metric cards, regional panel, "why this prediction" panel, and recommended actions panel all implemented matching the mockup layout.
- [ ] All data sourced through Part 10's shared data-fetching utility.
- [ ] Region-switching behavior implemented and refreshes all panels.
- [ ] Loading/error/empty states implemented per Part 10's conventions.
- [ ] Visual review against the mockup screenshot for color/layout fidelity (risk color semantics in particular).

## 6. Handoff note template

> Dashboard page implemented at route: <path>. Confirmed data sources: <API calls used>. Any gaps found in the Part 07 contract while building this page: <list, if any — feed back to Part 07 owner>.

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **Built** (step 6, uncommitted): the dashboard with the Maharashtra map, layers, table, cards, score button, and the 6-hourly refresh script; verified in the end-to-end demo. Deviations: the map has no district boundaries (no verified licensed source); the Forecast card makes 3 extra calls; no mockup in the repo to review against.

**Why:** the examiner asked for a Maharashtra map showing heatwave predictions and risk levels for places in Maharashtra (M4). §2.3 already planned a visual regional overview beside the regional table, and the map is that overview, so it fits without reshaping the page.

### R2.1 Regional Heatwave Risk panel → Maharashtra map
- Left: the shared `MaharashtraMap` (Part 10 R2.2) with every place from `GET /regions`, each coloured, labelled and shaped by its latest predicted risk class for the selected lead day. Right (stacked on small screens): the regional table (Area/Place, District, Temperature, Risk badge, valid date), extended from five Mumbai areas to all places, sortable by risk.
- **Lead-day switch** (Today / +1 / +2 / +3 days) over map and table, so the "next 1–3 days" horizon is visible across the state. Default: today.
- **Map layer switch**, all from our actual data for the selected lead day: **Predicted risk** (default; the stored model prediction, categorical risk scale), **Forecast max temperature** (Open-Meteo, °C, sequential scale), and **Departure from normal** (forecast Tmax − the place's IMD normal, the model's top feature, sequential scale with the 4.5 °C and 6.5 °C thresholds marked in the legend). The table shows all three columns at once, so switching the layer never hides data.
- **Freshness on the map itself:** the legend shows when the forecast was issued and when places were last scored. Stale places get the hollow marker (Part 10 R2.2), and places never scored show "no data" with the score-missing action (R2.3).
- **Model caveat until Part 05 R2:** while the production model is still the coastal-trained one, inland places' predicted risk carries "Model not yet validated for inland places" in the tooltip and legend. The forecast-temperature and departure layers have no such caveat, because they are observations and forecasts, not model output.
- **Explore and compare** (into Part 14 R2): the selected place's tooltip and table row offer **"Analyse"** (that place's history, patterns and predictions), and ticking up to four table rows enables **"Compare"** (side by side). The dashboard stays the entry point; the analysis lives on the Analytics page and is not duplicated here.
- **Division filter** (our proposal, from `regions.yaml` data): All / Konkan / Pune / Nashik / Chhatrapati Sambhajinagar / Amravati / Nagpur. It filters the table and zooms the map.
- The "DEMO DATA" tag stays while the weather feed is the committed sample or stale; the shell's stale-weather badge is unchanged.

### R2.2 Data sources (resolves §4's "minimum calls" requirement)
- **Two calls, independent of the number of places:** `GET /api/v1/predictions/latest-by-region?lead_days=` (Part 07 §B) feeds the predicted-risk layer, the table's risk column and the four metric cards. `GET /api/v1/weather?lead_days=` (all places, which the existing endpoint already supports) feeds the temperature and departure layers and columns. The selected place's entries are reused for the metric cards, with no extra per-place request.
- **Refresh:** the existing live policy (60 s poll, paused while hidden). "Last updated" comes from these queries automatically.

### R2.3 Decisions recorded (owner, 2026-10-20)
- **Row and marker click → select the place and stay on the dashboard.** Every panel re-focuses on that place. Each table row and map tooltip also has a separate "Details" link that opens the Prediction page for that place (`/predictions?region=<id>`). The command center stays the hub. This answers §3's "define exactly which".
- **Empty data → both a seeding CLI and an explicit button.** Places with no stored prediction are listed in an empty/partial state with **"Score places without a prediction"**, which calls `POST /predictions/batch` with `only_missing: true` and shows progress and the result. The `server` seeding CLI scores every place × lead 0–3 for demos and integration (Part 16 R2). The dashboard never scores silently on page view.
- **Verification environment:** until the v2 model is promoted, local verification runs the ML service from a scratch registry on the developer's platform (runbook, Troubleshooting). The committed registry is never changed for local work.

### R2.4 Unchanged
Page header, the four metric cards, "Why this prediction?" (condensed SHAP, linking to the Prediction page), Recommended Authority Actions, region switching through the global selector, and the loading/error/empty conventions.

### R2 acceptance criteria
- [ ] Map + table panel implemented with every place, risk colour + label + shape, lead-day switch and division filter.
- [ ] Map layer switch (predicted risk / forecast Tmax / departure) and the three table columns, all from stored data and forecasts; freshness shown in the legend; inland model caveat shown until Part 05 R2.
- [ ] "Analyse" and "Compare" open the Part 14 R2 views with the right places.
- [ ] Map, table and metric cards fed by exactly two calls (`latest-by-region` + all-places `weather`), verified in the network log.
- [ ] Marker and row click select the place and stay; the "Details" link opens the Prediction page with the right place.
- [ ] "Score places without a prediction" button implemented with progress, partial-failure reporting and rate-limit handling; seeding CLI documented in the runbook.
- [ ] Visual check: a place's colour on the map, its table badge, the metric card and the Prediction page all show the same risk class and probability.
