# frontend/

Web dashboard for Local Authority / Disaster Management Officials (Parts 10–14).

**Status:** Part 10 is done: the navigation shell, global state, the data layer, design tokens, the shared components and a `/design-system` showcase. The four pages are placeholders until Parts 11–14 replace them. Why it is built this way: [ADR 0009](../docs/decisions/0009-frontend-architecture.md).

Stack: Vite 7, React 19, TypeScript, React Router 7, TanStack Query 5, Tailwind CSS v4, shadcn/ui (Radix), Vitest + Testing Library.

```sh
npm ci                 # install exactly what package-lock.json pins (Node 22, see ../.nvmrc)
cp .env.example .env.local
npm run dev            # http://localhost:5173, expects the API at VITE_API_BASE_URL
npm test               # vitest (jsdom), no backend needed
npm run typecheck && npm run lint && npm run format:check
npm run build          # static assets in dist/
```

The backend's default `CORS_ALLOWED_ORIGINS` is `http://localhost:5173`, so run the dev server on that port (it is `strictPort`).

## Where things are

| Path                                  | What                                                                                                                                                                                                             | Rule for Parts 11–14                                                 |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `src/app/router.tsx`, `navigation.ts` | Routes (each a lazy child of the shell) and the four nav items                                                                                                                                                   | Point your route's `lazy` import at your page module                 |
| `src/components/layout/`              | `AppShell`: branding, nav, region selector, "last updated", stale-weather badge, account menu, sign-in dialog                                                                                                    | Never render a page-level header bar                                 |
| `src/components/shared/`              | `RiskBadge`, `StatusPill`, `MetricCard`, `ContributingFactorBar` / `FactorList`, `DataSourceTag`, `ActionList`, `Panel` / `PageHeader`, `ProtectedAction`, and `QueryState` with its loading/error/empty states  | Import these. Don't restyle risk or status per page                  |
| `src/design/`                         | `tokens.ts` (risk → tone, status → tone, type scale, spacing), `labels.ts` (names from `../config/feature_labels.json`, number formatting matching the Python code), `fixtures.ts` (contract-shaped sample data) | The risk → colour mapping lives here only                            |
| `src/styles/globals.css`              | Colour tokens for light and dark (`--tone-*`, `--risk-*`, `--chart-*`)                                                                                                                                           | Charts use `riskCssVar()`, not a library palette                     |
| `src/lib/api/`                        | `client.ts` (envelope, `ApiError`, timeout, bearer token), `endpoints.ts` (one function per route), `types.ts` (mirror of openapi.json)                                                                          | Change `types.ts` with any backend contract change                   |
| `src/lib/query/`                      | `hooks.ts` (one hook per read/write), `policy.ts` (refresh policy), `keys.ts`, `last-updated.ts`                                                                                                                 | Use the hooks. Never call `fetch` or set `refetchInterval` in a page |
| `src/state/`                          | `useRegion()`, `useSession()`, `useTheme()`                                                                                                                                                                      | Region-scoped queries read `useRegion().regionId`                    |

## Conventions

- **Colours:** pages and shared components use semantic classes (`bg-risk-severe`, `text-tone-warning-subtle-fg`, `text-muted-foreground`). ESLint fails on raw palette colours such as `bg-red-600`. `src/design/contrast.test.ts` keeps every pair at WCAG AA in both themes.
- **Numbers:** show API fields as they come. SHAP bars use `share_pct` and `direction` unchanged (`docs/ml/explainability.md` §3). Input values use `formatFeatureValue`, which rounds exactly like the backend's summary sentence.
- **Refresh:** see the table in `src/lib/query/policy.ts`. The dashboard polls (60 s, paused when the tab is hidden), an issued alert polls every 3 s while delivery is pending, and analytics only refreshes on demand.
- **Region:** one global selection. `?region=<id>` on any URL selects that region (dashboard → prediction drill-through) and is then removed from the address bar.
- **Session:** the token is kept in sessionStorage and ends at `expires_at` or on any 401, which reopens sign-in. Hiding a button is UX only. The API enforces auth.
- **Contract drift:** `src/lib/api/contract.test.ts` compares the fixtures with `../docs/api/openapi.json`. Regenerate openapi.json when the backend changes, and fix whatever fails.

Config: copy `.env.example` to `.env.local`. That file is git-ignored and must contain no secrets, because everything in it ends up in the bundle.
