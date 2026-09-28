# Part 14 — Frontend: Analytics (Trends & Insights) Page

**Depends on:** 10 (frontend architecture/design system), 07 (`GET /api/analytics`), 08 (historical data availability)
**Feeds into:** 16 (integration)
**Owner persona:** Frontend engineer

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
