# Part 15 — Authentication & Authorization

**Depends on:** 07 (backend API), 08 (`users` table)
**Feeds into:** 13 (alert issuing is a protected action), 10 (frontend session state), 16 (integration)
**Owner persona:** Backend engineer (with frontend coordination)

> **Revision 2 (2026-10-20, examiner feedback, M1):** user login is mandatory. It is implemented in the **Node.js API with users in MongoDB**, it is required for every application page and data endpoint, and it adds real logout. The mechanism, token shape and security requirements below are unchanged. Part 07's FastAPI login becomes the reference. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

## 1. Objective

Implement login and access control for the single defined persona in this system — Local Authority / Disaster Management Official — and gate every consequential write action (issuing alerts, in particular) behind it, per the use-case diagram in the project brief.

## 2. Scope decision for the mini-project

- The use-case diagram names one actor role ("Local Authority / Disaster Management Official"). Decide explicitly whether this project needs multiple distinct roles/permission levels (e.g., a read-only observer role vs. a full authority role that can issue alerts) or whether a single authenticated role is sufficient for the mini-project's scope. Recommend: implement a single role for the mini-project, but design the `users` table (Part 08) and the authorization check (Section 5) so an additional role could be added later without a structural rework.

## 3. Authentication mechanism

- Username/password (or email/password) login against the `users` table (Part 08), with passwords stored only as salted hashes, never plain text or reversibly encrypted.
- Session handling: choose a token-based approach (a signed token issued at login, sent by the frontend on subsequent requests) over server-side session storage, since it keeps the backend stateless per Part 07 Section 7's non-functional requirement.
- Token expiry and refresh: define a reasonable session length appropriate for authority users who may be actively monitoring during a heat event (long enough not to interrupt active use, short enough to limit exposure if a device is left unattended) — document the specific duration chosen and the refresh behavior (silent refresh vs. requiring re-login).

## 4. Endpoints

- `POST /api/auth/login` — accepts credentials, returns a session token on success, a generic (non-user-enumerating) failure message on invalid credentials.
- `POST /api/auth/logout` — invalidates the current token/session.
- A "current user" endpoint or token-embedded claim the frontend can use to populate the global session state (Part 10 Section 3) without a separate round-trip on every page load.

## 5. Authorization enforcement

- Define, per endpoint from Part 07's inventory, whether it requires authentication at all (most `GET` endpoints for dashboard/analytics data may reasonably be open within the deployed environment, or may also require auth — decide explicitly and document per endpoint) and which require it strictly (`POST /api/alerts`, at minimum, must require a valid authenticated session).
- Enforcement happens server-side as the source of truth (a middleware/dependency check on protected routes) — any frontend-side hiding of the "Issue Warning" button for logged-out users (Part 13) is a UX convenience only, never the actual security boundary.

## 6. Frontend integration points

- Login screen/flow (not detailed in the provided mockups, but required): a simple credential form, error handling for invalid login, and redirect to the dashboard on success.
- Global session state (Part 10) populated on login, cleared on logout, and checked by the nav shell (to show user identity/logout option) and by the Alerts page (to gate the "Issue Warning" action's availability and to attach the session token to that write request).
- Handle session expiry gracefully in the frontend: a request failing due to an expired token should redirect to login with a clear message, not fail silently or show a confusing generic error.

## 7. Non-functional / security requirements

- No credentials or tokens ever logged in plaintext (Part 07's logging strategy, Section 7, must explicitly exclude auth headers/credential fields).
- Brute-force protection on the login endpoint (basic rate limiting, per Part 07 Section 4's rate-limiting convention, applied specifically here).
- HTTPS-only transport assumed/enforced at the deployment level (Part 18) — tokens must never be sent over plaintext HTTP outside of local development.

## 8. Acceptance criteria / "done"

*Status checked against the code on 2026-10-20. Part 15 itself was never started, but Parts 07, 08 and 10 built part of it in FastAPI and the frontend foundation. Revision 2 re-implements it in Node.js + MongoDB (below), so these ticks describe the FastAPI reference, not the R2 deliverable.*

- [x] `users` table integration confirmed against Part 08's schema. *(FastAPI: `SqliteUserStore` on the `users` / `user_regions` tables, Part 08.)*
- [ ] Login/logout endpoints implemented with hashed-password verification. *(**Partly built.** `POST /auth/login` and `GET /auth/me` exist, with scrypt salted hashes, constant-time compare and the same answer for a wrong password or unknown user, all tested in `backend/tests/test_auth_and_startup.py`. **Logout is not built**: there is no endpoint and no revocation.)*
- [x] Session token mechanism implemented with a documented expiry/refresh policy. *(HMAC-SHA256 signed tokens, `AUTH_TOKEN_TTL_MINUTES` = 60, no refresh: re-login; documented in `docs/api/README.md` §1 and §8; expiry and tampering tested.)*
- [x] Per-endpoint auth requirement documented and enforced server-side for every endpoint in Part 07's inventory. *(For the Part 07 matrix: writes, `/auth/me` and `/alerts/{id}/attempts` require a token; reads are open by that design. Revision 2 changes the matrix to "login required everywhere", which is not built yet.)*
- [ ] Frontend login flow and global session state implemented. *(**Partly built** (Part 10): `SessionProvider` global state and a sign-in **dialog**. The login **screen** with redirect (§6) is not built; it is Part 10 R2.1, step 5.)*
- [ ] "Issue Warning" action in Part 13 confirmed to be both UI-gated and server-enforced. *(Server-enforced: yes (`POST`/`PATCH /alerts` need a token). UI gating: the `ProtectedAction` component exists, but the Alerts page (Part 13) is not built.)*
- [x] Session-expiry handling implemented gracefully on the frontend. *(Part 10 `SessionProvider`: the session ends at `expires_at` or on any 401 and reopens sign-in with "session expired"; tested in `frontend/src/state/state.test.tsx`.)*
- [x] Login endpoint rate-limited. *(10/min per IP, `RATE_LIMIT_LOGIN_PER_MINUTE`; tested.)*

## 9. Handoff note template

> Auth mechanism: <summary>. Token expiry: <duration>. Per-endpoint auth matrix documented at: <path>. Frontend session state populated via: <mechanism>. Part 13 and Part 16 can now assume real auth enforcement rather than mocked/open access.

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **Mostly built** (step 5, uncommitted): login, logout and `me` on Node.js + MongoDB, required for every data endpoint, with a frontend login page, route guard and server-side sign-out, verified live in a browser. ⏳ Open: the expiry warning before timeout, and "Issue Warning" UI gating (needs the Alerts page, step 8).

**Why:** the examiner made user login a must-have (M1), and the application API is now Node.js on MongoDB. The §2–§7 design (single role, signed token, server-side enforcement, rate-limited login, no credentials in logs) already fits. Revision 2 places it in Node and makes it cover the whole app.

### R2.1 Decisions
| Topic | Decision | Why |
|---|---|---|
| Scope (§2) | **One role, `official`**, with `role` stored on the user so a read-only `viewer` can be added later without restructuring | §2's recommendation, unchanged |
| Where | Node API (`server/`), users in MongoDB `users` (Part 08 R2) | M1 + M2 |
| Passwords | Salted adaptive hash (bcrypt family, cost ≥ 12); a wrong password and an unknown user take the same time and give the same message | §3, §7 |
| Token | Signed JWT (HS256, `JWT_SECRET`), claims `sub`, `role`, `jti`, `exp`; response shape unchanged: `{access_token, token_type: "bearer", expires_at, user}` | The Part 10 session code consumes it as is |
| Expiry (§3) | **60 minutes**, with no silent refresh: the frontend warns 5 minutes before expiry and the official signs in again. An active monitoring session survives a heat event's working block; an unattended device locks within the hour | Simple and documented; refresh tokens can be added later |
| Logout (§4) | `POST /auth/logout` writes the token's `jti` to `revoked_tokens` (TTL-indexed, removed at expiry); every authenticated request checks it | A real logout without server sessions |
| Current user (§4) | `GET /auth/me`, plus the user object in the login response, so no extra round-trip on page load | unchanged |
| Brute force (§7) | 10 login attempts per minute per IP (unchanged), plus a per-username lock of 15 minutes after 10 consecutive failures | M1 is now the front door, so it gets a second guard |
| Accounts | No self-registration. A `server` CLI creates, disables and resets officials. Local/test seed one demo official from env (as today); staging/production seed none | Authority accounts are issued, not signed up for |

### R2.2 Per-endpoint auth matrix (§5, rewritten for the Node API)
| Endpoint group | Auth |
|---|---|
| `POST /auth/login` | open, rate limited |
| `GET /health`, `GET /health/ready` | open (probes) |
| `GET /advisories` | open (public portal and display-board feed) |
| Everything else: `/regions`, `/weather`, `/predict`, `/predictions/*`, `/alerts*`, `/alert-channels`, `/analytics`, `/auth/me`, `/auth/logout` | **valid, unrevoked token** |
| ML service (Part 07 §A) | not public; service token from the Node API only |

This changes Part 07's original matrix, where reads were open. The reason: the examiner's login requirement, and the fact that the app now covers a whole state's data.

### R2.3 Frontend (Part 10 R2.1)
`/login` page, route guard on every page, logout in the account menu, the expiry warning, and a 401 → `/login` with "session expired". "Issue Warning" stays both UI-gated and server-enforced.

### R2 acceptance criteria
- [x] `users` and `revoked_tokens` collections with unique username and TTL indexes; passwords hashed, never logged. *(Migrations 5–6. The validator only accepts a bcrypt hash (a plain password insert is rejected, tested). Live: `$2b$12$…`, TTL `expireAfterSeconds: 0` on `expires_at`. Login bodies are never logged: the access log records method, path, status and user id only.)*
- [x] Login, logout and me implemented in Node with the unchanged token response shape; timing-equal failure path tested. *(`server/src/auth/service.ts`, `http/auth-routes.ts`. Wrong password, unknown user and disabled account give the identical 401 body. An unknown or disabled account still pays one bcrypt compare against a dummy hash (by construction; wall-clock timing is not asserted, since it is flaky in CI). `TokenOut`/`UserOut` fields are checked against `docs/api/openapi.json`.)*
- [x] Every endpoint enforces the R2.2 matrix (a test per endpoint group: no token, expired, revoked, valid). *(`server/src/auth.test.ts`: all 9 protected routes 401 without a session and work with one; expired, tampered, wrong-secret, `alg: none`, revoked (after logout) and disabled-account tokens refused; health/readiness open. Live: `/regions` 401 without a token, 200 with one, 401 after logout.)*
- [x] Login rate limit and per-username lockout tested. *(10/min per IP → 429 with Retry-After; 10 consecutive failures lock a username for 15 min, **including unknown usernames**, so the lock does not reveal which accounts exist; a success resets the count.)*
- [x] User-management CLI; no default user outside local/test; placeholder `JWT_SECRET` refused outside local/test. *(`npm run users -- list | create | reset-password | disable | enable`; passwords only on stdin, at least 12 characters. The demo official is seeded in local/test and deactivated elsewhere (tested). The JWT_SECRET rule dates from step 1.)*
- [ ] Frontend login flow, guard, logout and expiry handling done (Part 10 R2.1); E2E: login → dashboard → logout → protected page redirects to login. *(**Built and checked live in a browser** (scripted Playwright run, 2026-10-20): signed-out `/analytics?region=nagpur` → `/login?next=…`; wrong password → generic message; sign-in → back to Analytics with Nagpur selected; sign-out revokes the token server-side → `/login`; `/alerts` signed out → `/login`. Every data call carried the token and login did not. **Open:** the 5-minute expiry warning (expiry already ends the session and returns to `/login` with "session expired"), and a committed E2E suite (step 11).)*
- [x] Auth matrix documented in `docs/api/README.md`. *(§1 Authentication, Revision 2 paragraph.)*
