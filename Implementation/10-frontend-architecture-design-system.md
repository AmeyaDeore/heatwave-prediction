# Part 10 — Frontend Architecture & Design System

**Depends on:** 07 (API contract must exist, even if not fully implemented), 01 (repo/environment)
**Feeds into:** 11, 12, 13, 14 (each individual page)
**Owner persona:** Frontend engineer

## 1. Objective

Establish the shared foundation every page-level plan (11–14) builds on: the frontend tech stack, routing/navigation shell, shared components, visual design system, and state/data-fetching conventions — so each page can be implemented independently without re-deciding these basics.

## 2. Navigation shell (matches the UI mockups exactly)

The application has one persistent top navigation bar present on every screen, containing, in order:
1. Product identity/branding ("Climate Intelligence").
2. Four primary nav items: **Dashboard**, **Predictions**, **Alerts**, **Analytics** — matching the four screens in Parts 11–14 exactly.
3. Current selected region/location display (e.g., "Mumbai, Maharashtra") — this is a global, persistent selection that affects the data shown on every page, so it must live in shared/global state, not be re-implemented per page.
4. A "last updated" timestamp indicator on data-heavy screens.

Define this navigation shell as one shared layout component that every page renders inside of, rather than each page implementing its own header.

## 3. Global state and data-fetching conventions

- **Selected region** — global state, changeable from the nav shell, read by every page's data-fetching logic.
- **Authenticated user/session** — global state, populated after login (Part 15), read by the nav shell (to show/hide protected actions) and by any page requiring auth for write actions (e.g., issuing an alert).
- **Data fetching pattern** — pick one consistent approach for calling the backend API (Part 07): a shared HTTP client with the base API URL from environment configuration, consistent loading/error/success state handling, and a consistent retry/refetch convention for "last updated" style live data (dashboard, weather).
- **Polling vs. manual refresh** — decide, per page, whether data auto-refreshes on an interval (reasonable for the dashboard's live risk indicator) or only on demand (reasonable for analytics/historical views) — document this decision here so it's consistent rather than ad hoc per page.

## 4. Design system

### 4.1 Color semantics (derived directly from the mockups)
Define a small, fixed palette used consistently across all four pages so risk severity is always visually unambiguous:
- **Green** — Normal / low risk / success states (e.g., "Normal Conditions" in the risk distribution, "READY" delivery status).
- **Orange/Amber** — Heatwave / medium-high risk / warning states.
- **Red** — Severe Heatwave / highest risk / critical alert states, also used for the brand accent bar seen at the bottom of every slide/screen.
- **Neutral grays/blues** — structural chrome (cards, borders, secondary text, the "Climate Intelligence" nav branding).

This mapping (risk class → color) must be defined **once**, as a shared design token, and referenced by every page (dashboard risk badges, prediction page risk banner, alerts severity tags, analytics risk-distribution bars) — never redefined independently per page, or the palette will drift.

### 4.2 Typography and spacing
- Establish a type scale (heading sizes for page titles like "Heatwave Command Center," card titles, body text, small metadata labels like "DEMO DATA" tags) and a consistent spacing unit, applied uniformly across all cards.

### 4.3 Shared components to build once, reuse everywhere
- **Risk badge** — a colored pill/label showing risk class (Normal/Heatwave/Severe Heatwave), used on the dashboard's regional table, the prediction page's main banner, and the alerts list.
- **Metric card** — a small card showing a label + big value + optional delta/sub-label (used for "Current Temperature," "Prediction Confidence," "Relative Humidity," etc. throughout).
- **Contributing-factor bar** — a horizontal bar showing a factor name and a proportional/percentage bar with a signed value, used for the SHAP explanation display (Prediction page) — this component directly consumes Part 06's output contract.
- **Data-source tag** ("DEMO DATA" / "AI EXPLAINED") — a small inline label used throughout the mockups to distinguish live/demo data and AI-derived content; keep this as a reusable, configurable component since it appears on nearly every card.
- **Action list item** — a numbered recommended-action row with an icon (used on both the dashboard and prediction pages for "Recommended Authority Actions").
- **Status pill** — for alert/delivery status (READY / NOTIFIED / PENDING / FAILED / DRAFT / ISSUED), color-mapped consistently with Section 4.1's semantics extended to operational statuses.

## 5. Responsiveness and accessibility baseline

- Define target device classes (the mockups are clearly desktop/dashboard-oriented, but confirm whether a tablet/mobile-responsive requirement exists for field use by disaster-response teams, since this materially affects card-layout decisions on every page).
- Baseline accessibility requirements: color is never the only signal for risk severity (pair color with text labels, as the mockups already do with explicit "SEVERE"/"HIGH"/"NORMAL" text); sufficient contrast on colored badges; keyboard navigability of the nav shell and forms.

## 6. Error, loading, and empty states (defined once, applied everywhere)

- **Loading state** convention for cards awaiting data (e.g., a skeleton/placeholder rather than a blank card).
- **Error state** convention when an API call fails (a clear, non-technical message plus a retry action, not a raw error dump).
- **Empty state** convention (e.g., "Analytics" page with no historical data yet, or "Alerts" page with no alerts issued).

## 7. Non-functional requirements

- No page-level plan (11–14) should need to redefine color semantics, shared components, or navigation — if a page's plan seems to require this, that's a signal this part's design system is incomplete and should be revised first.
- The design system should be implementable and demonstrable on its own (e.g., a simple style-guide/component-showcase view) before any individual page is built, so inconsistencies are caught early rather than after four pages have diverged.

## 8. Acceptance criteria / "done"

- [ ] Navigation shell component built and rendering the four nav items + region selector + branding.
- [ ] Global state conventions (region, session) implemented and documented.
- [ ] Data-fetching pattern (including polling/refresh policy) implemented as a shared utility.
- [ ] Color-semantic tokens defined and documented (risk → color mapping is the single most important one).
- [ ] All shared components in Section 4.3 built and demonstrable in isolation.
- [ ] Loading/error/empty state components built and documented as the default for all data-driven cards.

## 9. Handoff note template

> Shared component library location: <path>. Design tokens (colors/type/spacing) at: <path>. Global state approach: <summary>. Data-fetching utility at: <path>. Parts 11–14 should import from here rather than reimplementing any of the above.
