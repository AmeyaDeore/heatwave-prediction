# Part 12 — Frontend: Prediction (AI Model Output) Page

**Depends on:** 10 (frontend architecture/design system), 06 (SHAP contract), 07 (`POST`/`GET` prediction endpoint)
**Feeds into:** 16 (integration)
**Owner persona:** Frontend engineer

## 1. Objective

Implement the detailed, single-region "Heatwave Prediction" screen — the page whose entire purpose is to make one prediction fully explainable, matching the UI mockup.

## 2. Page contents, section by section

### 2.1 Page header
- Title: "Heatwave Prediction," subtitle: "AI-powered short-term heatwave risk assessment," current selected region shown alongside.

### 2.2 Main risk banner
- A prominent, color-coded (per Part 10's risk-color semantics) banner showing: risk class (e.g., "SEVERE HEATWAVE"), region, risk probability (e.g., "91% RISK — Predicted probability"), and the forecast window ("Next 1–3 Days — Predicted probability" / forecast label).
- This is the single most visually dominant element on the page and should use the full-width risk-color treatment shown in the mockup (a colored banner/border, not just a small badge).

### 2.3 Input feature summary row
- Four metric cards showing the actual input values that drove this prediction: Maximum Temperature, Relative Humidity, Wind Speed, Temperature Deviation — using the shared Metric Card component, sourced directly from the "raw input feature values" field in Part 07's `POST /api/predict` response contract (never recompute or guess these client-side).

### 2.4 "Why did the AI make this prediction?" panel
- The full SHAP explanation, using the shared Contributing-Factor Bar component: every top factor (not the condensed 2–3 shown on the dashboard) with its signed proportional bar, labeled with the "AI EXPLAINED" and "DEMO DATA" tags as appropriate.
- Below the bars, the templated natural-language summary sentence from Part 06 Section 3 ("The model predicts a high likelihood of severe heatwave conditions because of...").

### 2.5 Recommended Authority Response panel
- The numbered action list (shared component from Part 10), labeled "ACT NOW," specific to this prediction's risk class — same underlying data source/mapping as the dashboard's version (Part 11 Section 2.5), reused here, not reimplemented.

## 3. Interaction behavior

- This page should be reachable both directly (via the "Predictions" nav item, defaulting to the currently selected global region) and via navigation from the dashboard's "why this prediction" panel (Part 11 Section 2.4) for a specific region — confirm both entry points pass/set the correct region.
- Consider whether this page should support re-running/refreshing the prediction on demand (a manual "recompute" action) versus only ever showing the latest persisted prediction from the database — decide explicitly; recommend showing the latest persisted prediction by default (consistent with the rest of the system's read model) with an optional explicit refresh action if a live recompute is desired.

## 4. Non-functional requirements

- The SHAP factor bars must render correctly for both positive and negative contributions (differing bar direction/color, matching the mockup's green-positive/other-negative example with Wind Speed shown as a small negative contributor) — verify this explicitly against a real negative-contribution example, not just positive ones, since that's an easy edge case to miss.
- Given this page's purpose is trust and transparency, every displayed number (probability, confidence, each factor's contribution) must trace directly to a field in Part 07's API response — no client-side derived or rounded-differently duplicate values that could disagree with the dashboard's version of the same prediction.

## 5. Acceptance criteria / "done"

- [ ] Risk banner, input feature summary, full SHAP explanation panel, and recommended-response panel implemented matching the mockup layout.
- [ ] Both positive and negative SHAP contributions render correctly.
- [ ] Page reachable via both direct nav and dashboard drill-through, with correct region context in both cases.
- [ ] Numbers displayed on this page are verified consistent with the same prediction's numbers shown elsewhere (dashboard condensed panel, analytics if applicable).

## 6. Handoff note template

> Prediction page implemented at route: <path>. Entry points verified: <direct nav, dashboard drill-through>. Any SHAP-rendering edge cases found: <list, if any>.
