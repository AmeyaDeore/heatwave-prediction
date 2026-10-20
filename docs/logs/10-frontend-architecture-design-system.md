# Log 10: Frontend architecture & design system

| | |
|---|---|
| Plan | [Implementation/10-frontend-architecture-design-system.md](../../Implementation/10-frontend-architecture-design-system.md) |
| Status | Complete against the plan's checklist. The four pages are placeholders for Parts 11–14 |
| Date(s) | Built 2026-10-09; verified against the real backend and documented 2026-10-20 |
| Branch / commits | `part-10/frontend-architecture` (uncommitted at the time of writing) |
| Tests | 145 frontend (Vitest, 8 files), all new. Python suite unchanged: 281 passed, 9 skipped on this machine (see Verification) |

## Summary

Part 10 built the shared frontend that every page builds on. It is a Vite + React 19 + TypeScript app with a single navigation shell, global region and session state, a typed API client, one data hook per endpoint with a documented refresh policy, a semantic colour system with one risk → colour mapping, the six shared components from §4.3, and default loading, error and empty states. Everything is shown on a `/design-system` page. The four nav routes render placeholders with their final titles, so region switching, deep links and "last updated" already work end to end. Parts 11–14 replace one route's `lazy` import each.

## What was built

| Path (under `frontend/`) | Role |
|---|---|
| `package.json`, `vite.config.ts`, `tsconfig*.json`, `eslint.config.js`, `.prettierrc.json`, `components.json`, `index.html`, `public/favicon.svg` | Toolchain. `@` → `src/`, `@config` → `../config/` (the shared label table, never copied). Vendor chunks split. ESLint adds typescript-eslint, react-hooks, and a rule that fails on raw Tailwind palette colours in pages and shared components |
| `src/app/` | `router.tsx` (every page is a lazy child of `AppShell`; `/design-system`; 404), `navigation.ts` (the four nav items, `RouteHandle`), `providers.tsx` (theme → query client → session → region → tooltip) |
| `src/components/layout/` | `AppShell` (branding, nav, stale-weather badge from `/health/ready`, region selector, "last updated" with refresh, account menu, footer with the model version, brand accent bar, skip link), `RegionSelector`, `LastUpdated`, `UserMenu` (theme, design system, sign in/out), `SignInDialog`, `RouteErrorBoundary` |
| `src/components/shared/` | `RiskBadge`, `StatusPill`, `MetricCard`, `ContributingFactorBar` + `FactorList` (diverging bar from `share_pct`/`direction`, with an "Estimated" tag for imputed values), `DataSourceTag` (presets: Demo data, Live, Stale data, AI explained, Act now), `ActionList`, `Panel` + `PageHeader`, `ProtectedAction`, `states.tsx` (`LoadingState`, `ErrorState`, `EmptyState`, `QueryState`) |
| `src/components/ui/` | shadcn/ui primitives (alert, badge, button, card, dialog, dropdown-menu, empty, input, label, progress, select, separator, skeleton, sonner, spinner, tooltip) |
| `src/design/` | `tokens.ts` (`RISK_TONE`, `STATUS_TONE`, `TONE_STYLE`, `riskCssVar`, type scale, spacing), `labels.ts` (names from `config/feature_labels.json`; `formatFixed` copies Python's round-half-to-even), `factors.ts`, `icons.ts` (action → icon), `fixtures.ts` (contract-shaped samples) |
| `src/styles/globals.css` | Light and dark tokens: `--tone-*`, `--risk-{normal,heatwave,severe}-*`, `--chart-*`, `--nav-*`, type sizes, exposed to Tailwind |
| `src/lib/api/` | `client.ts` (`apiRequest`: base URL, envelope unwrapping, `ApiError`, 15 s timeout, caller cancellation, bearer token; an ok envelope on a 503 such as readiness is still data), `endpoints.ts` (all 15 routes), `types.ts` (mirror of openapi.json), `errors.ts` (`describeError` → title, description, retryable, request-id reference) |
| `src/lib/query/` | `hooks.ts` (one hook per read/write; `useAlert` polls 3 s while delivery is pending; mutations update the cache), `policy.ts` (refresh policy table), `keys.ts`, `last-updated.ts`, `client.ts` (queries retry transient failures (network, timeout, 5xx/503, 429) up to twice, honouring Retry-After; other 4xx and all mutations never retry) |
| `src/state/` | `region.tsx` (URL → localStorage → `VITE_DEFAULT_REGION`, repaired against `GET /regions`), `session.tsx` (sessionStorage token, ends at `expires_at` or on a 401 and reopens sign-in; `withToken` for writes), `theme.tsx` |
| `src/pages/` | `design-system-page.tsx` (the §7 showcase) and `placeholder-pages.tsx` (Dashboard, Predictions, Alerts, Analytics with their final titles, plus Not found) |
| `src/test/` | Setup, `render` helper with providers, a fetch mock, and `python-format-vectors.json` (values formatted by the Python code, for the parity test) |

**Docs:** [ADR 0009](../decisions/0009-frontend-architecture.md), `frontend/README.md` (rewritten from "tooling only"), the Part 10 plan checklist, `docs/README.md`, and `docs/local-dev-runbook.md` (steps 7–8, two macOS troubleshooting entries, a validation-log row).
**Dependency change:** the frontend now has runtime dependencies (React, React Router, TanStack Query, Radix, lucide, sonner, Tailwind tooling). The npm lockfile is updated. No backend or ML change.
**Contract changes:** none. The frontend consumes `docs/api/openapi.json` as it is.

## Key decisions and why

The full table is in [ADR 0009](../decisions/0009-frontend-architecture.md). The main points:

- **TanStack Query for all server data, React context only for region, session and theme.** Polling, focus refetch, retry and caching are solved once, and §3's "polling vs. manual refresh" becomes one table (`policy.ts`) instead of per-page choices.
- **Refresh policy:** the dashboard and readiness poll every 60 s (configurable, minimum 15 s, paused while the tab is hidden). The Prediction page shows the latest *stored* prediction, and "Recompute" (`POST /predict`) is explicit and rate limited. An issued alert polls every 3 s while `delivery_summary.pending > 0`, then stops (Part 09's contract). Analytics refreshes only on demand.
- **One risk → colour mapping, enforced:** `RISK_TONE` plus CSS variables. ESLint rejects raw palette classes and a test checks WCAG AA contrast in both themes. Colour is never the only signal: the badge always carries the label from `config/feature_labels.json` plus an icon.
- **Numbers never disagree with the API:** metric cards format with `formatFixed`, which matches Python's `f"{x:.Nf}"` (round half to even). For example 31.25 shows "31.2" in both places, not "31.3". This is tested against vectors the Python code produced.
- **Region in global state with deep links:** `?region=` selects a region and is then removed from the URL. This gives Part 11's drill-through to Part 12 without either page owning the region.
- **Session in sessionStorage**, ended at `expires_at` or on any 401, which reopens sign-in with a "session expired" message (Part 15 §6). `ProtectedAction` shows a "Sign in to …" button instead of hiding the action. This is UX only, because the API enforces auth.
- **Stale-but-visible:** if a background refetch fails, the data stays and "last updated" shows its age. The shell shows a "Weather data stale" badge whenever readiness reports it.

## Verification

All of this ran on macOS (Apple Silicon), Node 24.14:

```
cd frontend
npm run typecheck        -> clean
npm run lint             -> clean
npm run format:check     -> All matched files use Prettier code style!
npm test                 -> 8 files, 145 passed
                            (contrast 51, labels/format parity 31, shared components 16, API client 13,
                             openapi contract 10, state 11, shell 9, query client 4)
npm run build            -> built in 2.6 s; react 69 kB gz, router 32 kB, radix 26 kB, vendor 32 kB,
                            each page a separate chunk
```

Python suite, to confirm nothing outside `frontend/` changed:

```
DYLD_FALLBACK_LIBRARY_PATH=.venv/.../sklearn/.dylibs .venv/bin/python -m pytest -q
  -> 281 passed, 9 skipped in 29 s
```

The 9 skips are the tests that need the production bundle, which is git-ignored and was not on this machine. Without the `DYLD_FALLBACK_LIBRARY_PATH` workaround every test fails at import, because `libomp` is not installed (runbook, Troubleshooting).

**Against the real backend.** `heatwave-train run` produced run `20261020T104511Z-d89b8a` with the same hyperparameters as the committed run, but with a different XGBoost SHA-256 and prediction fingerprint (`acc1e3b5…`, committed `f8c2334b…`; library versions identical to `uv.lock`). Training is reproducible only on the same platform. So the run was evaluated (macro-F1 0.8867, 0 severe days predicted NORMAL, all gates pass), promoted and explained in a **scratch registry** (`MODEL_REGISTRY_DIR` outside the repo), and the API ran on it with a scratch SQLite DB. `git status ml/` stayed clean. Results:

- `GET /health/ready` → ready, `weather_data: "stale"` (the committed sample was issued 2026-09-28). The shell showed the "Weather data stale" badge and the model version in the footer.
- The region selector listed the 5 regions from `GET /regions`. `/alerts?region=colaba` selected Colaba and removed the parameter from the URL.
- `/design-system` rendered all 9 sections.
- Sign-in contract: a wrong password gave 401 "Incorrect username or password.", the demo user gave 200 and `/auth/me` 200. The CORS preflight from `http://localhost:5173` for `POST /alerts` with `authorization` was allowed.
- The backend access log for the session showed only the expected calls (`/regions`, `/health/ready` polling, `/auth/login`, `/auth/me`, `/predictions/latest` 404 → empty state). Vite logged no errors.
- The browser check was cut short: the shared Playwright browser was being driven by another client at the same time, so the sign-in form was checked over HTTP, not by clicking. `app-shell.test.tsx` and `state.test.tsx` cover the UI side of sign-in, expiry and 401 handling.

## Deviations from the plan and issues found

- **The production model can't be reproduced on Apple Silicon.** Part 04's "bit-for-bit reproducible" holds only within a platform. A fresh Mac checkout cannot satisfy `ml/registry/production.json` without a copy of the original bundle. This is documented in the runbook. Whether to commit or publish the bundle, or record a per-platform note in Part 04/05, is an open item.
- **"HIGH" wording from the mockups is not used.** The vocabulary is fixed at Normal / Heatwave / Severe Heatwave (CLAUDE.md), so the badges show those labels.
- **The sign-in dialog stands in for a login page.** Part 15 §6 asks for a login screen. The dialog satisfies the session contract, and Part 15 may add a route without changing `useSession()`.
- **Untracked tooling at the repo root:** `package.json` / `package-lock.json` / `node_modules/` (a `shadcn` CLI dev dependency) and `.mcp.json` came from setting up the shadcn MCP server, and `.playwright-mcp/` holds browser-session screenshots. None of these is part of the app. Decide whether to commit or ignore them.

## Open items / follow-ups

- **Part 11:** there is no batch "latest prediction for every region" endpoint (docs/api §8). Part 11 §4 asks to flag this to Part 07 instead of firing one request per region. Also, nothing creates predictions on a schedule: `/predictions/latest` is 404 until someone calls `POST /predict`, so the dashboard starts empty.
- **Part 15:** logout is client-side only (there is no `/auth/logout` or token revocation), and only the seeded demo user exists.
- **Node:** `.nvmrc`/`engines` pin Node 22. This machine has 24. It works, but CI (Part 18) should use 22.
- Running totals in the log index said 289 Python tests. This tree collects 290 (281 + 9 skipped here).

## Handoff

> Shared component library location: `frontend/src/components/shared/` (primitives in `src/components/ui/`). Design tokens (colors/type/spacing) at: `frontend/src/styles/globals.css` (CSS variables) and `frontend/src/design/tokens.ts` (risk/status → tone, type scale, spacing). Global state approach: React context for region (`useRegion`, persisted, `?region=` deep links), session (`useSession`, sessionStorage token, `withToken` for protected writes) and theme. Server data lives only in TanStack Query. Data-fetching utility at: `frontend/src/lib/api/` (client + endpoints + types) and `frontend/src/lib/query/hooks.ts` (refresh policy in `policy.ts`). Parts 11–14 should import from here rather than reimplementing any of the above, and replace their placeholder by pointing the route's `lazy` import in `src/app/router.tsx` at the new page module.

## Update 2026-10-20: plan Revision 2

The same day, the plan was revised for the examiner's mandatory features ([log](2026-10-20-examiner-feedback-plan-revision.md), [ADR 0010](../decisions/0010-mern-application-layer.md)). Part 10 as built stays valid. Its Revision 2 section adds a login page and route guard, the shared `MaharashtraMap` component, region grouping by division, and the API base URL pointing at the Node.js API. Those items are not implemented yet. The "Open items" above about the batch endpoint and empty dashboard are now settled in Part 07 §B and Part 11 R2.

## Update 2026-10-20: Revision 2 step 5, login page, route guard, Node API base URL

R2.1 is built: the `/login` page, the `RequireSession` guard on every shell route, the API client's session bridge (the token on every call, a 401 ends the session), the region list waiting for a session, and sign-out revoking the token server-side. R2.4: `VITE_API_BASE_URL` and the `env.ts` default now point at the Node.js API (`:4000`), and `RegionOut` gains the optional `division`/`kind`/`parent`. Test helpers render signed in by default (`{ signedIn: false }` to opt out). 13 new tests, 158 total; checked live in a browser (details in [log 15](15-authentication-authorization.md)). Still pending in R2: the map component and grouping places by division (step 6).
