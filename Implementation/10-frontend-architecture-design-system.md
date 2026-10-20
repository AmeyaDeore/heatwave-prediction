# Part 10 — Frontend Architecture & Design System

**Depends on:** 07 (API contract must exist, even if not fully implemented), 01 (repo/environment)
**Feeds into:** 11, 12, 13, 14 (each individual page)
**Owner persona:** Frontend engineer

> **Revision 2 (2026-10-20, examiner feedback):** the foundation below is complete and stays. Revision 2 adds a login page and route guard (M1), a shared Maharashtra map component (M4), place grouping by division in the region selector, and points the API base URL at the Node API. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

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

*Status checked 2026-10-20: all six items are built and tested (145 tests) in the working tree on branch `part-10/frontend-architecture`, **not yet committed**. Log: `docs/logs/10-frontend-architecture-design-system.md`.*

- [x] Navigation shell component built and rendering the four nav items + region selector + branding. *(`frontend/src/components/layout/app-shell.tsx`: "Climate Intelligence", Dashboard / Predictions / Alerts / Analytics, region selector fed by `GET /regions`, "last updated" on data screens, stale-weather badge from `GET /health/ready`, account menu, and the brand accent bar. Below `lg` the nav moves to a scrollable second row.)*
- [x] Global state conventions (region, session) implemented and documented. *(`src/state/`: region persisted in localStorage with `?region=` deep links, repaired against the region list; session token in sessionStorage, ended at `expires_at` or on a 401, which reopens sign-in. ADR 0009, `frontend/README.md`.)*
- [x] Data-fetching pattern (including polling/refresh policy) implemented as a shared utility. *(`src/lib/api/client.ts` + `endpoints.ts` (envelope, `ApiError`, timeout, token) and `src/lib/query/hooks.ts` with the per-data-kind table in `policy.ts`: dashboard polls 60 s, issued alert 3 s while pending, analytics on demand.)*
- [x] Color-semantic tokens defined and documented (risk → color mapping is the single most important one). *(`src/styles/globals.css` + `src/design/tokens.ts` `RISK_TONE`: NORMAL green, HEATWAVE amber, SEVERE_HEATWAVE red; ESLint bans raw palette colours; WCAG AA contrast asserted in both themes.)*
- [x] All shared components in Section 4.3 built and demonstrable in isolation. *(Risk badge, metric card, contributing-factor bar (diverging, negative values tested), data-source tag, action list item, status pill, all on `/design-system`.)*
- [x] Loading/error/empty state components built and documented as the default for all data-driven cards. *(`src/components/shared/states.tsx`: `<QueryState>` with skeleton, plain-language error + Retry + request id, empty state; 404 can count as empty.)*

## 9. Handoff note template

> Shared component library location: <path>. Design tokens (colors/type/spacing) at: <path>. Global state approach: <summary>. Data-fetching utility at: <path>. Parts 11–14 should import from here rather than reimplementing any of the above.

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **In progress.** ✅ R2.1 login page, route guard, logout and token on every call (step 5); ✅ R2.4 base URL → Node API. ⏳ R2.2 map component and R2.3 place grouping (step 6). (The original Part 10 foundation above is built.)

**Why:** login (M1) and the Maharashtra map (M4) are shared by several pages, so by §7's own rule they belong in the design system, not in one page. Everything already built (shell, state, data layer, tokens, components, states) stays as is. The React stack is already the "R" in MERN.

### R2.1 Login page and route guard (M1)
- A `/login` route outside the shell's protected area: a credential form, the generic invalid-login message, a rate-limit message on 429, and redirect to the page originally requested (default: dashboard).
- **Every page requires a session** (Part 15 R2). An unauthenticated visit redirects to `/login`, and an expired session or any 401 returns there with "Your session expired, sign in again". The existing `SessionProvider`, `withToken` and expiry timer are reused. The sign-in dialog remains for re-authentication without losing a half-filled alert form.
- **Sign out** in the account menu calls `POST /auth/logout`, then clears the session.
- **Read hooks attach the token** (today only writes do). This is a change in `src/lib/query/hooks.ts` through `withToken`, so pages stay untouched.

### R2.2 Maharashtra map component (M4)
- A shared `MaharashtraMap` in `src/components/shared/`, used by the dashboard (Part 11 R2) and analytics (Part 14 R2).
- **Rendering: a plain SVG map, no map library** (revised 2026-10-20, to keep to the existing stack). The Maharashtra state and district boundaries are a GeoJSON file in `config/geo/`, from an openly licensed source recorded with its licence, simplified to a small file. The component projects it to SVG paths with a fixed equirectangular projection fitted to Maharashtra's bounding box, which is accurate enough at state scale and needs no projection library. Every colour comes from the existing tokens, the map works offline, and there are no tile requests and no API keys. A street-level map is out of scope. If it is ever needed, a tile library can be added behind this same component interface.
- **What it draws:** district outlines (division boundaries emphasised); one marker per place from `GET /regions`; and an optional **district fill** for analysis views (Part 14 R2), only for districts that contain a monitored place. Districts without a place stay neutral and are never filled by guesswork.
- **Layers passed in by the page, not fetched by the component:** each place gets a value plus a scale. The scale is either *categorical risk* (NORMAL / HEATWAVE / SEVERE_HEATWAVE, from `RISK_TONE`) or *sequential* (for example forecast Tmax, departure from normal, or heatwave days per year), with a legend generated from the scale. Pages decide what is shown; the component only renders.
- **Markers:** fill colour from the **existing risk tokens** (`riskCssVar`, never a library palette). Each marker carries the risk label and a distinct shape per class, because colour is never the only signal (§5). A place with no data shows a neutral "no data" marker; a place whose data is stale shows a hollow marker with "stale" in its tooltip.
- **Interaction:** hover or focus shows a tooltip (place, district, division, the layer value with units, valid date or period); click or Enter selects that place as the global region. Markers are keyboard-reachable in a logical order (by division, then name), and a **table equivalent** is always rendered next to the map, for screen readers and small screens.
- **Mumbai areas** (`kind: area`) appear as one Mumbai marker at state scale, plus a **Mumbai inset** showing the five areas, because the areas are a few kilometres apart and would overlap on a state map.
- **Legend and loading/error/empty states** use the existing components. It is shown on `/design-system` with fixture data for each scale type.

### R2.3 Place selection
- The nav region selector lists places grouped by `division` (Part 02 R2), with type-ahead search, since 18+ places no longer fit a short list. The selection, persistence and `?region=` deep-link behaviour is unchanged.

### R2.4 Configuration
- `VITE_API_BASE_URL` → the Node API (`http://localhost:4000` locally). This switch happens once, when the Node API passes the contract tests (Part 07 §B transition). Until then the frontend keeps calling FastAPI.
- `src/lib/api/types.ts` gains the additive R2 fields (`division`, `kind`, `parent`, `origin`, `place_comparison`, the batch and latest-by-region shapes). `contract.test.ts` keeps them in step with the generated `openapi.json`.

### R2 acceptance criteria
- [ ] `/login` page, route guard, logout and expiry redirect implemented and tested (component + E2E). *(**Built and tested** at the component level: `src/pages/login-page.tsx`, `src/components/layout/require-session.tsx`; safe `?next=` (no open redirect); 401/429 messages; "signed out" and "session expired" notices; 13 new tests. Checked live in a browser. A committed E2E suite is step 11.)*
- [x] Read queries authenticated through `withToken`; a 401 on any query returns to `/login`. *(Implemented one level lower than `withToken`: a session bridge in `src/lib/api/client.ts` attaches the token to every call (registered in a layout effect, so even the first queries carry it), and a 401 on a call that carried it ends the session as "expired". The region list waits for a session. Tested.)*
- [ ] `MaharashtraMap` built as SVG with district outlines, risk and sequential scales, district fill, markers with labels and shapes, stale/no-data markers, tooltip, keyboard selection, table equivalent, Mumbai inset, legend and states; shown on `/design-system`.
- [ ] Boundary GeoJSON committed with source and licence, simplified (target under 300 KB); no new runtime dependency and no third-party network requests.
- [ ] Region selector grouped by division with search.
- [ ] Contrast and raw-colour lint rules extended to the map component.
