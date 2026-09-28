# Part 11 — Frontend: Dashboard Overview Page

**Depends on:** 10 (frontend architecture/design system), 07 (`GET /api/weather`, latest predictions)
**Feeds into:** 16 (integration)
**Owner persona:** Frontend engineer

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
