# Part 09 — Notification Service

**Depends on:** 07 (backend API triggers this), 08 (delivery status persisted here)
**Feeds into:** 13 (Alert Management page reflects delivery status), 16 (integration)
**Owner persona:** Backend engineer

> **Revision 2 (2026-10-20, examiner feedback, M5):** the alert system runs on **Node.js + MongoDB**. The notification service built in this part (Python) is ported to the Node API with the same channel mapping, templates, recipients, retry policy, status rules and audit trail, all read from the same `config/` files. A new rule connects it to the prediction workflow: a HEATWAVE or SEVERE_HEATWAVE prediction can create a *draft* alert for an official to review. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

## 1. Objective

Build the service responsible for actually delivering an issued alert to its selected channels (Email / SMS / App, as named in the architecture diagram, mapping to the UI's more granular channel list: Public Mobile Alert, Government Portal, Public Display Boards, Emergency Services, Hospitals & Health Centres) and for tracking delivery status back into the database.

## 2. Channel scope for this project

- Treat **Email** and **SMS** as the two concrete, externally-integrated channels for the mini-project (both have straightforward third-party provider APIs).
- Treat **App** (in-app/portal notification, public display boards, etc.) as an internal channel — "delivering" to this channel means writing a record the frontend itself polls/displays (e.g., a public advisory banner), not an external API call.
- Document this mapping explicitly: which of the UI's five listed distribution channels map to which underlying delivery mechanism (external email, external SMS, or internal/in-app), since not all five need a real third-party integration to be functionally complete for a mini-project demo.

## 3. Provider selection (Email / SMS)

- Choose one transactional email provider and one SMS provider (or a single provider offering both, if available) based on: availability of a straightforward API, reasonable free/trial tier for a mini-project, and reliable delivery tracking (delivery/failure webhooks or status polling).
- Credentials for these providers are environment configuration (per Part 01), never hard-coded.
- Document a fallback/mock provider mode for local development and testing, so the whole team isn't burning real provider quota/credits while building and testing the rest of the system.

## 4. Message content and templating

- Define one message template per channel type, parameterized by: region, severity, and the public advisory text (matching the UI mockup's "SEVERE HEATWAVE ALERT — MUMBAI... avoid prolonged outdoor exposure, stay hydrated..." style message).
- Keep templates separate from delivery logic, so the wording can be edited without touching the dispatch code — this also allows a future non-English localization pass without restructuring the service.
- SMS templates specifically need a length constraint (a defined maximum character count) since SMS has hard technical limits — plan a truncation/summarization rule distinct from the full email/portal message.

## 5. Dispatch flow

1. Backend (Part 07) calls the notification service with: the alert identifier, target region, severity, message text, and the list of channels selected at alert-issue time.
2. For each selected channel, the notification service resolves the right recipient list (e.g., a configured distribution list per region/channel — this is itself a small piece of reference data to define: who receives SMS alerts for a given region, which portal/display-board integration endpoint applies, etc.).
3. Dispatch is attempted per channel independently — one channel's failure must not block another channel's delivery.
4. Each channel's outcome (success/failure, and if available, a provider-side delivery status) is written back to the `alert_channel_deliveries` table (Part 08), updating that channel's status from `READY`/`PENDING` to `NOTIFIED` or `FAILED`.

## 6. Retry and failure handling

- Define a retry policy for transient failures (e.g., a small number of retries with backoff) distinct from permanent failures (e.g., invalid recipient) which should not be retried indefinitely.
- Failed deliveries after exhausting retries must remain visible as `FAILED` in the database (Part 08) — this status is what the Alert Management screen (Part 13) surfaces to the authority user, so they know to intervene through another channel.
- Log every dispatch attempt (channel, timestamp, outcome, provider response/error) for auditability — this matters for a public-safety system where "did the alert actually go out" needs to be answerable after the fact.

## 7. Asynchronous processing consideration

- Decide whether dispatch happens synchronously within the `POST /api/alerts` request/response cycle, or is handed off to a background task/queue so the API can respond quickly while delivery happens in the background. For a mini-project's scale, a simple background-task approach (rather than a full message-queue infrastructure) is proportionate — document this as the deliberate choice, with a note that a real message queue would be the natural next step at larger scale.
- If asynchronous, define how the frontend learns about status changes after the initial response — either by polling `GET /api/alerts` (simplest, matches the rest of this project's read model) or a push mechanism (likely unnecessary complexity here).

## 8. Non-functional requirements

- Notification dispatch must never fail silently — every attempt has a recorded, queryable outcome.
- Recipient lists and provider credentials must be configurable per environment (so testing never accidentally messages real emergency-services distribution lists).
- Dispatch latency for the internal/in-app channel should be near-instant; external channels are allowed provider-dependent latency but should have a documented reasonable timeout after which the attempt is marked failed rather than hanging indefinitely.

## 9. Acceptance criteria / "done"

- [x] Channel-to-delivery-mechanism mapping documented (Section 2). *(`mechanism:` per channel in `config/alert_channels.yaml`, validated at startup and exposed by `GET /alert-channels`: public_mobile + emergency_services → SMS, hospitals → email, government_portal + display_boards → in-app advisory. `docs/notifications/README.md` §1.)*
- [x] Email and SMS providers selected, with a mock/local mode for development. *(SendGrid + Twilio over stdlib HTTP with timeouts; `NOTIFICATIONS_MODE=mock` is the default, sends nothing and can simulate failures; `live` refuses to start without every credential and never runs with `APP_ENV=test`. The committed recipient list is `.invalid` addresses and Twilio test numbers only. §2, §4.)*
- [x] Message templates defined per channel type, separated from dispatch logic. *(`config/notification_templates.yaml`, one per mechanism; SMS capped at 160 GSM-7 characters by shortening only the advisory text. §3.)*
- [x] Dispatch flow implemented per Section 5, writing status back to the database. *(Per-region recipient lists, channels dispatched independently, each outcome written to `alert_channel_deliveries` as PENDING → NOTIFIED/FAILED. §5.)*
- [x] Retry policy implemented and distinguishes transient vs. permanent failure. *(Per recipient: timeout/429/5xx retried 3× with 2 s/4 s backoff; other 4xx and missing recipients are never retried. §6.)*
- [x] Dispatch attempts logged for audit purposes. *(Append-only `notification_attempts` table (migration 0002) plus a JSON log line per attempt; `GET /alerts/{id}/attempts` (protected). §7.)*
- [x] Synchronous-vs-async decision made and documented, with the frontend status-refresh approach defined accordingly. *(Background worker thread; the API returns PENDING and Part 13 polls `GET /alerts/{id}` while `delivery_summary.pending > 0`; PENDING is resumed at startup. A real queue is the documented next step. §8, ADR 0008.)*

## 10. Handoff note template

> Providers configured: <email provider>, <SMS provider> (mock mode available via: <config flag>). Channel mapping: <summary>. Dispatch is <sync/async>; status refresh approach: <summary>. Part 13 (Alert Management UI) can now build against real per-channel status values from the database.

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **Built in reduced form** (scope freeze, 2026-10-20, uncommitted): alerts on Node.js + MongoDB (create, list, view, edit draft, issue; idempotent create; issued alerts immutable; PENDING → NOTIFIED in the background; resume after restart). **Delivery is mock**: each channel is recorded as delivered and nothing is sent. Not ported: real SendGrid/Twilio, retries, the attempts audit, advisories, and the prediction → auto-draft rule (out of the frozen scope). The alert form is pre-filled from the place's latest prediction and stores its `prediction_id`.

**Why:** the examiner requires the alert system on Node.js and MongoDB (M5). The Python service is complete and tested, so it becomes the **executable specification**. Its behaviour, documented in `docs/notifications/README.md` and ADR 0008, and its 36 test cases are what the Node port must reproduce. Nothing about *what* is sent, to whom, or how failure is shown changes.

### R2.1 What is ported unchanged (same `config/` files, same semantics)
- **Channel → mechanism mapping** from `config/alert_channels.yaml`: public_mobile and emergency_services → SMS; hospitals → email; government_portal and display_boards → in-app advisory.
- **Templates** from `config/notification_templates.yaml`, including the 160-character GSM-7 SMS rule that shortens only the advisory text, and ASCII-only SMS. Placeholders are checked at startup.
- **Recipients** from `NOTIFICATION_RECIPIENTS_FILE`, with per-region overrides and E.164/email validation. The committed file stays `.invalid` addresses and test numbers only.
- **Providers:** SendGrid (email) and Twilio (SMS) over plain HTTPS with explicit timeouts (Node's built-in `fetch`, no vendor SDKs), plus the mock provider with simulated failures. `NOTIFICATIONS_MODE=mock` is the default; `live` refuses to start without every credential and never in test.
- **Retry:** per recipient; transient (timeout, 429, 5xx) retried 3× with 2 s / 4 s backoff; permanent failures never retried.
- **Status rules:** a channel is NOTIFIED only if every recipient got it, otherwise FAILED with "k of n failed: reason". Unexpected errors are stored with a generic reason.
- **Audit:** every attempt is written to MongoDB `notification_attempts` (append-only, Part 08 R2) and to the JSON log. `GET /alerts/{id}/attempts` is protected.

### R2.2 Dispatch on Node.js
- **PENDING first:** issuing writes the alert as ISSUED with every channel PENDING in **one atomic document write** (Part 08 R2.1), then queues the alert id. The response returns at once, and the frontend polls `GET /alerts/{id}` while `delivery_summary.pending > 0` (unchanged contract).
- **Worker:** an in-process async queue in the Node API (one process, proportionate to scale). Each channel is delivered independently and its result written back to that channel's array element as it lands.
- **Crash safety:** at startup the API re-queues every ISSUED alert with PENDING channels (at-least-once, as before). Advisories stay unique per alert × channel, so they cannot duplicate.
- **Inline mode** (`NOTIFICATIONS_DISPATCH=inline`) is kept for tests.
- **Scale note unchanged:** with more than one API process, move the job (an alert id) to a real queue.

### R2.3 Connection to the prediction workflow (new)
When the Node API stores a prediction (Part 07 §B: `POST /predict`, batch scoring, or the seeding CLI), it applies the **draft-suggestion rule**:
- **Trigger:** the risk class is HEATWAVE or SEVERE_HEATWAVE for lead 0–3, **and** the place has no DRAFT or READY alert, and no ISSUED alert at the same or higher severity within a cool-down window (`ALERT_SUGGESTION_COOLDOWN_HOURS`, default 24).
- **Effect:** a DRAFT alert with `origin: auto_draft`, the prediction's region and severity, `prediction_id` set (so the "why" stays traceable to the SHAP factors), the advisory pre-filled from the template for that severity, and a default channel selection per severity (SEVERE: all five; HEATWAVE: public mobile, portal, hospitals). The default selection lives in config, not code.
- **Never dispatches.** Only an official's explicit "Issue Warning" sends anything (Part 13 §4, unchanged). A suggestion that is no longer warranted (for example a later NORMAL prediction for the same place and day) is marked as superseded in the list, never deleted.
- **Switchable:** `ALERT_SUGGESTIONS=on|off` (default on), so the behaviour can be shown or disabled per environment.
- Labelling-spec §4 places duration rules ("two consecutive HEATWAVE forecasts") in the alerting layer. A duration condition can be added to this trigger later as a config option. It is not required for R2.

### R2 acceptance criteria
- [ ] Node notification service implements R2.1 against the same `config/` files; startup validation of templates, recipients and channel mechanisms.
- [ ] Every scenario covered by the Python suite (`backend/tests/test_notifications.py`) is ported as a Node test and passes: mapping, rendering and truncation, recipients, retry/backoff, give-up, permanent failure, partial-recipient failure, no recipients, idempotent advisories, HTTP classification, request shapes, mock/live safety, background PENDING → NOTIFIED, slow channel not blocking, startup resume, append-only audit, audit endpoint auth.
- [ ] Draft-suggestion rule (R2.3) implemented and tested: trigger, de-duplication, cool-down, supersession, on/off switch, and **no dispatch without an explicit issue**.
- [ ] End to end on MongoDB in mock mode: score a place to HEATWAVE → a draft appears → an official issues it → channels move PENDING → NOTIFIED/FAILED → attempts recorded.
- [ ] `docs/notifications/README.md` and ADR 0008 updated with a Node section that points at ADR 0010.
