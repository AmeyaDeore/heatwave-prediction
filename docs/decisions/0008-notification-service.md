# ADR 0008: Notification service

- **Status:** Accepted
- **Date:** 2026-10-07
- **Part:** 09 (notification service)

## Context

An issued alert must reach its selected channels, and every delivery outcome must be recorded and visible to the official (Part 13). The service must be safe to develop and test without messaging real people or spending provider credit. The UI lists five channels, but only some of them need a third-party integration.

## Decisions

| Topic | Decision | Why |
|---|---|---|
| Channel mapping | `mechanism` per channel in `config/alert_channels.yaml`: `public_mobile`, `emergency_services` → sms; `hospitals` → email; `government_portal`, `display_boards` → in_app | Two real integrations cover the five channels. In-app is a database row that the portal and boards poll |
| Providers | SendGrid (email), Twilio (SMS), called through the stdlib `urllib` with explicit timeouts | Free/trial tiers, simple APIs, message ids for delivery tracking. No SDK dependencies |
| Dev safety | `NOTIFICATIONS_MODE=mock` by default. `live` refuses to start with any credential missing, and always refuses when `APP_ENV=test`. The committed recipient list is `.invalid` addresses and Twilio magic numbers only | Testing must never reach a real roster or burn credit |
| Templates | One YAML file, one template per mechanism. SMS is capped at 160 GSM-7 characters by shortening only the advisory text | Wording can change without code. Severity, region and reference always survive the cut |
| Retry | Per recipient: transient errors (timeout, 429, 5xx) retried 3× with 2 s/4 s backoff; permanent errors (other 4xx, no recipients) never retried | Retrying a bad number cannot help, while a brief outage often clears |
| Channel status | NOTIFIED only if every recipient succeeded, otherwise FAILED with "k of n failed: reason" | A partly delivered warning must not look complete |
| Audit | Append-only `notification_attempts` table (triggers) plus a JSON log line per attempt | "Did it go out?" has a durable, tamper-resistant answer |
| Sync vs async | Background worker thread with an in-memory queue. The API returns PENDING and the UI polls `GET /alerts/{id}` | The request is not held hostage by a slow provider. Polling matches the rest of the read model |
| Crash safety | PENDING is committed before queueing, and startup re-queues ISSUED alerts with PENDING channels (at-least-once). Advisories are unique per alert and channel | A crash can cause a duplicate SMS, never a silently lost warning |

## Alternatives considered

- **Synchronous dispatch in the request:** the simplest option, but a provider timeout would stall the official's "Issue Warning" click for up to about 30 s per recipient. It is kept as `NOTIFICATIONS_DISPATCH=inline` for tests.
- **FastAPI `BackgroundTasks`:** these run after the response, but in the request's worker with no queue to drain at shutdown and no way to resume. A dedicated thread does both.
- **Celery/RQ + Redis:** the right tool at scale, but it adds infrastructure that a single-process mini-project does not need. The job payload (an alert id) is already queue-ready.
- **WebSocket/SSE push for status:** unnecessary complexity when polling a few times per issued alert is enough.
- **Vendor SDKs (twilio, sendgrid):** they add heavy dependencies for two POST requests.

## Consequences

- Schema version 2 (`0002_notifications.sql`). Back up before migrating a deployed database (docs/database §6).
- `POST/PATCH ... ISSUED` responses now normally show channels `PENDING`, and Part 13 must poll while `delivery_summary.pending > 0`.
- `GET /alert-channels` now includes `mechanism`. There are new endpoints `GET /advisories` and `GET /alerts/{id}/attempts` (protected).
- Provider delivery webhooks are not consumed yet, so `NOTIFIED` means "accepted by the provider".
