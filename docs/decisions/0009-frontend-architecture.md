# ADR 0009: Frontend architecture and design system

- **Status:** Accepted
- **Date:** 2026-10-20
- **Part:** 10 (frontend architecture & design system)

## Context

Four pages (Parts 11–14) are built by possibly different people, against one API contract (`docs/api/README.md`). They must share navigation, the selected region, the session, one way to call the API, and one risk-colour vocabulary. If any of these were re-decided per page, the pages would drift apart. The user is a Local Authority / Disaster Management Official watching a desktop "command center", sometimes from a tablet in the field.

## Decisions

| Topic | Decision | Why |
|---|---|---|
| Build tool and language | Vite 7 + React 19 + TypeScript (strict) | Static assets that any host can serve (Part 18), fast dev server, and types that mirror the API contract |
| Routing | React Router 7 (`createBrowserRouter`), every page a lazy child of one `AppShell` route | One shared layout (§2), and each page ships as its own chunk |
| Server state | TanStack Query 5. One hook per endpoint in `src/lib/query/hooks.ts`. Query keys built in one place (`keys.ts`) | Loading, error, retry, cache and polling are solved once. A page never calls `fetch` or sets its own interval |
| Refresh policy | Decided per kind of data in `src/lib/query/policy.ts`: reference data once per session; live data (dashboard, readiness) polled every `VITE_DASHBOARD_POLL_INTERVAL_MS` (60 s, minimum 15 s) and paused while the tab is hidden; the Prediction page shows the latest stored prediction, with an explicit "Recompute"; alerts list on focus; an issued alert polled every 3 s while `delivery_summary.pending > 0`; analytics manual only | §3 asks for this to be decided once. It matches the backend's read model and Part 09's polling contract |
| HTTP client | `apiRequest` in `src/lib/api/client.ts`: base URL from env, the envelope unwrapped once, every failure turned into one `ApiError` (`kind`: client / upstream / internal / network / timeout), a 15 s timeout, and the bearer token attached only when passed | One place handles the envelope and the error taxonomy (docs/api §1) |
| Global client state | React context: `RegionProvider` (persisted in localStorage, `?region=` deep links, repaired against `GET /regions`), `SessionProvider` (token in sessionStorage, ends at `expires_at` or on the first 401 and reopens sign-in), `ThemeProvider` | Small, typed, and with no extra dependency. Server data stays in the query cache, not in context |
| UI primitives | shadcn/ui (Radix primitives, copied into `src/components/ui/`) on Tailwind CSS v4 | Accessible behaviour (focus, keyboard, ARIA) without writing it by hand. The source is in the repo, so it can be changed |
| Design tokens | CSS custom properties in `src/styles/globals.css`, in layers: tone palette → risk aliases (`--risk-normal/heatwave/severe`) → Tailwind utilities. `src/design/tokens.ts` maps risk class and operational status to tones, once | §4.1: one risk → colour mapping. Charts (Part 14) read the same variables through `riskCssVar()` |
| Colour enforcement | An ESLint rule fails on any raw Tailwind palette colour (`bg-red-600` …) in pages and shared components. `contrast.test.ts` checks every text/background pair against WCAG AA in light and dark | Drift is caught by the build, not in review |
| Labels | Risk-class and feature names imported from `config/feature_labels.json`, the table the ML code and backend use. Number formatting mirrors Python's `f"{x:.Nf}"` (round half to even), checked against vectors generated from Python | A value on the dashboard and in the API's summary sentence never disagree by a rounding step (Part 12 §4) |
| States | `<QueryState>` (skeleton → plain-language error with Retry → empty → content). A failed background refetch keeps the data on screen, and the shell's "last updated" shows its age | §6 is defined once. Part 11 §4 asks for stale-but-labelled data rather than a blank screen |
| Showcase | `/design-system` renders every token and shared component with contract-shaped fixtures | §7: the design system can be shown before any page is built |
| Devices | Desktop first. The layout works from 360 px: below `lg`, nav items move to a scrollable second row | Field teams may use tablets or phones (§5) |

## Alternatives considered

- **Next.js:** server rendering and API routes are not needed. The backend is FastAPI, and a static build is simpler to host and to point at each environment.
- **Redux / Zustand for everything:** most of the state is server data, which TanStack Query already caches. Only the region, session and theme are client state, and three small contexts cover them.
- **A component library with its own theme (MUI, Chakra):** overriding its palette everywhere would fight §4.1's single mapping. shadcn primitives take their colours from our tokens.
- **Generating the TypeScript types from openapi.json:** this adds a codegen step to the build. Hand-written types plus `contract.test.ts`, which fails when a fixture and openapi.json disagree, catch the same drift.

## Consequences

- Parts 11–14 replace a placeholder in `src/app/router.tsx` with their page module and use only `src/lib/query/hooks.ts`, `src/components/shared/` and `src/design/`.
- A backend contract change must update `src/lib/api/types.ts` and the fixtures in the same PR, or `contract.test.ts` fails.
- `VITE_*` values are compiled into the public bundle and must never hold a secret.
- The sign-in dialog and session provider are the seam that Part 15 extends (logout, refresh, roles). The session contract stays the same.
