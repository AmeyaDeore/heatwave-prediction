# Part 09 — Notification Service

**Depends on:** 07 (backend API triggers this), 08 (delivery status persisted here)
**Feeds into:** 13 (Alert Management page reflects delivery status), 16 (integration)
**Owner persona:** Backend engineer

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

- [ ] Channel-to-delivery-mechanism mapping documented (Section 2).
- [ ] Email and SMS providers selected, with a mock/local mode for development.
- [ ] Message templates defined per channel type, separated from dispatch logic.
- [ ] Dispatch flow implemented per Section 5, writing status back to the database.
- [ ] Retry policy implemented and distinguishes transient vs. permanent failure.
- [ ] Dispatch attempts logged for audit purposes.
- [ ] Synchronous-vs-async decision made and documented, with the frontend status-refresh approach defined accordingly.

## 10. Handoff note template

> Providers configured: <email provider>, <SMS provider> (mock mode available via: <config flag>). Channel mapping: <summary>. Dispatch is <sync/async>; status refresh approach: <summary>. Part 13 (Alert Management UI) can now build against real per-channel status values from the database.
