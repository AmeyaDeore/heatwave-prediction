# Part 15 — Authentication & Authorization

**Depends on:** 07 (backend API), 08 (`users` table)
**Feeds into:** 13 (alert issuing is a protected action), 10 (frontend session state), 16 (integration)
**Owner persona:** Backend engineer (with frontend coordination)

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

- [ ] `users` table integration confirmed against Part 08's schema.
- [ ] Login/logout endpoints implemented with hashed-password verification.
- [ ] Session token mechanism implemented with a documented expiry/refresh policy.
- [ ] Per-endpoint auth requirement documented and enforced server-side for every endpoint in Part 07's inventory.
- [ ] Frontend login flow and global session state implemented.
- [ ] "Issue Warning" action in Part 13 confirmed to be both UI-gated and server-enforced.
- [ ] Session-expiry handling implemented gracefully on the frontend.
- [ ] Login endpoint rate-limited.

## 9. Handoff note template

> Auth mechanism: <summary>. Token expiry: <duration>. Per-endpoint auth matrix documented at: <path>. Frontend session state populated via: <mechanism>. Part 13 and Part 16 can now assume real auth enforcement rather than mocked/open access.
