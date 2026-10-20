# Log 15: Authentication & authorization (Revision 2: login on Node.js + MongoDB)

| | |
|---|---|
| Plan | [Implementation/15-authentication-authorization.md](../../Implementation/15-authentication-authorization.md), Revision 2 (the teacher's mandatory **user login**, M1) |
| Status | Mostly complete (step 5). Open: the 5-minute expiry warning; "Issue Warning" UI gating (needs the Alerts page, step 8); a committed E2E suite (step 11) |
| Date | 2026-10-20 |
| Branch | `part-10/frontend-architecture` (uncommitted) |
| Tests | server +40 (`server/src/auth.test.ts`), frontend +13; totals: server 134, frontend 158, Python 337 (+3 skipped, 6 pre-existing errors) |

## Summary
Login is now required for the whole application. Officials sign in on a `/login` page; every data endpoint of the Node.js API refuses a request without a valid, unrevoked token; signing out revokes the token on the server. Accounts live in MongoDB with bcrypt hashes and are issued through a CLI (no self-registration). The frontend now talks to the Node.js API instead of FastAPI.

## What was built
| Path | Role |
|---|---|
| `server/src/auth/service.ts` | `AuthService` (bcrypt cost 12; the same 401 for a wrong password, an unknown or a disabled user, with a dummy-hash compare for unknown/disabled; JWT HS256 with sub/role/jti/exp, 60 min; authenticate checks signature, algorithm, expiry, revocation and an active account); `LoginGuard` (a per-username lock after N consecutive failures, counted for unknown names too) |
| `server/src/db/users.ts`, migrations 5–6 | `users` (unique username; the validator accepts only bcrypt hashes; a single `official` role); `revoked_tokens` (TTL on `expires_at`) |
| `server/src/http/auth-routes.ts` | `POST /auth/login` (rate limited, Retry-After), `GET /auth/me`, `POST /auth/logout`; `requireAuth` in front of every other `/api/v1` route |
| `server/src/app.ts` | CORS with the FastAPI rules; readiness now passes through `explainer_id`/`weather_issued_at` for the shell footer |
| `server/src/bootstrap.ts` | `seedDemoUser`: local/test seed `official`; anywhere else the account is deactivated |
| `server/src/cli/users.ts` | `npm run users -- list | create | reset-password | disable | enable` (passwords on stdin only, at least 12 characters) |
| `frontend/src/lib/api/client.ts` | session bridge: the session token on every call; a 401 on a call that carried it ends the session ("expired"); login opts out |
| `frontend/src/state/session.tsx`, `region.tsx` | the bridge is registered in a layout effect (the first queries already carry the token); the region list waits for a session |
| `frontend/src/pages/login-page.tsx`, `components/layout/require-session.tsx`, `app/router.tsx` | `/login` outside the shell; the guard on every other route; safe `?next=` (`safeNext`, no open redirect) |
| `frontend/src/components/layout/user-menu.tsx` | sign-out calls `POST /auth/logout`, then ends the session |
| `frontend/.env.example`, `src/lib/env.ts` | API base URL → `http://localhost:4000` (Node.js API) |

## Key decisions
- **Login everywhere** (Part 15 R2.2), the examiner's requirement. Open: login, health and readiness only.
- **No silent refresh;** 60-minute tokens. Expiry ends the session and returns to `/login` with "session expired".
- **Lockout without enumeration:** failures are tracked per typed username whether or not it exists, and the locked answer is the same 429 for everyone.
- **Token attached in the HTTP client, not per hook,** so no page can forget it and a 401 is handled in one place.
- **`openapi.json` generation from Node deferred to step 9** (Part 07 R2 deviation): until Node serves alerts and analytics, a Node-generated spec would drop contracts the frontend relies on. A server test pins Node's `TokenOut`/`UserOut` to the current spec instead.

## Verification
```
server: typecheck, lint, format clean; npm test -> 8 files, 134 passed
frontend: typecheck, lint, format clean; npm test -> 8 files, 158 passed; npm run build ok (login page chunk 1.4 kB gz)
live API (Node + FastAPI role ml + MongoDB 7.0.31):
  /regions without a token -> 401; wrong password -> 401 "Incorrect username or password."
  login -> me (user_demo) -> /regions 18 places -> latest-by-region 18 items -> logout -> same token 401
  CORS preflight from http://localhost:5173 -> allowed with Authorization,Content-Type,X-Request-ID
  MongoDB: users.official hash $2b$12$..., 1 revoked token under the TTL index, 6 migrations
live browser (Playwright, fresh tab, one scripted run):
  /analytics?region=nagpur -> /login?next=%2Fanalytics%3Fregion%3Dnagpur
  wrong password -> "Incorrect username or password."; correct -> /analytics, "Nagpur, Maharashtra"
  selector lists 18 places; footer "Model xgboost-20261020T104511Z-d89b8a"
  sign out -> POST /auth/logout with the token -> /login "You have signed out."; /alerts -> /login?next=%2Falerts
  console: only the deliberate wrong-password 401
```

## Open items
- 5-minute expiry warning; "Issue Warning" UI gating (step 8); E2E suite committed under `tests/` (step 11).
- The sign-in dialog stays for re-authentication on the Alerts page (step 8).
- Rate limits and the lockout are per process (one Node process, as planned).

## Handoff
> Auth mechanism: bcrypt + JWT HS256 on the Node.js API, users in MongoDB, logout revokes the token id. Token expiry: 60 min, no refresh. Per-endpoint auth matrix: `docs/api/README.md` §1 (Revision 2). Frontend session state is populated by `/login` and attached to every call by the API client's session bridge. Part 13 can rely on real auth enforcement; its "Issue Warning" uses `ProtectedAction` plus the server check.
