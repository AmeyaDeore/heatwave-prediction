# Notification service (Part 09)

How an issued alert reaches people, and how anyone can later check that it did.

| | |
|---|---|
| Plan | [Implementation/09-notification-service.md](../../Implementation/09-notification-service.md) |
| Code | [`backend/src/heatwave_api/notifications/`](../../backend/src/heatwave_api/notifications/) |
| Config | `config/alert_channels.yaml` (mechanism), `config/notification_templates.yaml` (wording), `config/notification_recipients.yaml` (who) |
| Schema | `0002_notifications.sql`: `notification_attempts`, `public_advisories` |
| Decision record | [ADR 0008](../decisions/0008-notification-service.md) |

## 1. Channel → delivery mechanism

The UI offers five distribution channels. Each maps to one of three mechanisms, set by `mechanism:` in `config/alert_channels.yaml`:

| UI channel (`id`) | Mechanism | What "delivered" means |
|---|---|---|
| Public Mobile Alert (`public_mobile`) | **sms** (external) | SMS to the region's public subscriber list |
| Government Portal (`government_portal`) | **in_app** (internal) | A row in `public_advisories`; the portal polls `GET /api/v1/advisories` |
| Public Display Boards (`display_boards`) | **in_app** (internal) | Same, so board controllers poll the same endpoint |
| Emergency Services (`emergency_services`) | **sms** (external) | SMS to the region's emergency-services duty numbers (urgent, read on the move) |
| Hospitals & Health Centres (`hospitals`) | **email** (external) | Email to the region's health desks (longer text, forwarded internally) |

Only SMS and email call a third party. A real cell-broadcast (CAP) feed for "Public Mobile Alert" is outside a mini-project's reach; SMS to a subscriber list is the stand-in. Changing a channel's mechanism is a one-line YAML edit; adding a mechanism is code (a provider plus a template).

## 2. Providers and modes

| Mechanism | Provider | Why |
|---|---|---|
| email | **SendGrid** (v3 Mail Send) | Free tier (100/day), a simple JSON API, `X-Message-Id` plus event webhooks for delivery tracking |
| sms | **Twilio** Programmable Messaging | Trial credit, magic test numbers, message `sid` plus status callbacks, Indian destinations supported |

`NOTIFICATIONS_MODE`:

- **`mock`** (default everywhere): `MockProvider` logs the message and keeps it in an in-memory outbox. Nothing leaves the process, so no quota or credit is used. Recipients ending `.fail`/`0000` simulate a permanent failure and `.retry`/`9999` a transient one, so the FAILED and retry paths can be shown in a demo.
- **`live`**: the real providers. Startup **refuses** if any of `EMAIL_PROVIDER`, `EMAIL_API_KEY`, `EMAIL_FROM_ADDRESS`, `SMS_PROVIDER`, `SMS_ACCOUNT_SID`, `SMS_API_KEY`, `SMS_SENDER_ID` is empty, and refuses outright when `APP_ENV=test`. Credentials come only from the environment (Part 01).

Staging and production log a warning at startup when they run in mock mode.

## 3. Templates (`config/notification_templates.yaml`)

There is one template per mechanism, filled from `severity_label`, `region_name`, `district`, `state`, `message`, `alert_id` and `issued_at` (shown in IST). The wording lives only in this file, so it can be edited, or localised later, without touching dispatch code. A placeholder typo stops startup.

Example SMS, from the mockup's style:

```
SEVERE HEATWAVE ALERT - Mumbai: Severe heatwave expected. Avoid prolonged outdoor exposure between 12 PM and 4 PM, stay hydrated, check on... Ref HW-2026-0001
```

**SMS length rule.** `sms.max_chars: 160` is one GSM-7 segment. If the rendered SMS is longer, only the official's `message` is shortened, at a word boundary, ending in `...`. Severity, region and the alert reference always survive. The template is kept to plain ASCII on purpose: one em dash or smart quote switches the whole SMS to UCS-2, where a segment holds only 70 characters. Email and in-app messages carry the full text.

## 4. Recipients (`NOTIFICATION_RECIPIENTS_FILE`)

For each external channel the file gives a `default` list and optional per-region `regions.<id>` lists. A region's own list replaces the default, and duplicates are removed. Numbers must be E.164 and addresses must look like email addresses, or startup fails.

The committed file is the **development list**. Every address is on the reserved `.invalid` domain and every number is a Twilio magic test number, and a test asserts this. Even `live` mode run from a laptop cannot reach a real person. A deployment points `NOTIFICATION_RECIPIENTS_FILE` at its own file, kept out of git because it holds officials' phone numbers. A channel with no recipients for a region **fails** that delivery ("no sms recipients configured for kurla"). It is never skipped silently.

## 5. Dispatch flow

```
POST/PATCH ... status=ISSUED
  └─ AlertService._issue: save ISSUED + every channel PENDING (one transaction)
     └─ dispatcher.submit(alert_id) ──► response 201/200 (channels PENDING)
                                         │
  worker thread: AlertService.deliver(alert_id)
     for each PENDING channel (independently; one failure never stops the rest):
        NotificationService.send(alert, channel)
           in_app → publish_advisory (idempotent per alert+channel)
           sms/email → render template → resolve recipients → per recipient:
                         provider.send with retry policy, every attempt audited
        repo.update_delivery(alert, channel, NOTIFIED|FAILED, detail)  ◄─ UI polls
```

A channel is `NOTIFIED` only if **every** recipient got it. Otherwise it is `FAILED`, with a detail such as `1 of 2 email recipients failed: mailbox does not exist`.

## 6. Retry policy

| Failure | Examples | Handling |
|---|---|---|
| Transient (`TransientError`) | timeout, connection/DNS error, HTTP 429, HTTP 5xx | retried, up to `NOTIFICATION_MAX_ATTEMPTS` (3) per recipient, waiting `NOTIFICATION_BACKOFF_SECONDS × 2^(n-1)` (2 s, 4 s) |
| Permanent (`PermanentError`) | HTTP 400/401/403/404 (invalid number, bad key, unverified sender), no recipients configured | not retried |
| Unexpected exception in a provider | a bug | treated as transient; the stored detail is generic ("unexpected provider error") and the traceback goes to the log only |

Every provider call has an explicit timeout (`NOTIFICATION_TIMEOUT_SECONDS`, 10 s). The worst case for one recipient is therefore about 3 × 10 s + 6 s of backoff, after which the channel is marked `FAILED` and never hangs. The in-app mechanism is a single local insert and completes in milliseconds.

## 7. Audit trail

Every attempt writes one row to `notification_attempts`: alert, channel, mechanism, provider, recipient, attempt number, outcome (`SUCCESS` / `TRANSIENT_FAILURE` / `PERMANENT_FAILURE`), sanitised detail, provider message id, start time and duration. The same fields go to the JSON log (`heatwave_api.notifications`, "notification attempt"). The table is **append-only**: triggers reject UPDATE and DELETE. If the database write itself fails, the log line is the fallback record and delivery continues.

- `GET /api/v1/alerts/{id}/attempts` (**protected**: it lists recipients) returns the trail for one alert.
- `GET /api/v1/advisories?region_id=&since=&limit=20` (public) returns the published advisories, newest first.

So "did the warning go out, to whom, and when?" can always be answered from the database.

## 8. Synchronous or asynchronous: background, with polling

**Decision: dispatch runs in the background** (`NOTIFICATIONS_DISPATCH=background`, the default). One in-process worker thread with an in-memory queue does the work. `POST`/`PATCH` returns at once with every channel `PENDING`. The worker writes each channel's result as it lands and moves the alert's `updated_at` forward.

**How the frontend learns the outcome: polling.** The Alert Management page (Part 13) polls `GET /api/v1/alerts/{id}` (or the list) every few seconds while `delivery_summary.pending > 0`, then stops. This is the same read model as the rest of the app. Push (WebSocket/SSE) would add complexity for no real gain at this scale.

**Crash safety.** PENDING rows are committed before the job is queued. On startup, `AlertService.resume_pending()` queues again every ISSUED alert that still has a PENDING channel, and shutdown drains the queue (up to 30 s). Delivery is therefore **at-least-once**: a crash in the middle of a send can repeat an SMS, which is the right side to err on for a public warning. Advisories cannot duplicate (unique per alert and channel).

**Why not a real queue.** A single API process with a handful of officials does not need Redis or Celery and their extra moving parts. The job is already just an alert id, so moving to a real message queue (Redis + RQ/Celery, SQS) is a small change. It becomes necessary when there is more than one API process, high volume, or a need for scheduled retries that survive a restart without the startup sweep.

`NOTIFICATIONS_DISPATCH=inline` delivers inside the request, so the response already carries the final statuses. Tests use it, and it helps when debugging.

## 9. Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `NOTIFICATIONS_MODE` | `mock` | `mock` / `live` |
| `NOTIFICATIONS_DISPATCH` | `background` | `background` / `inline` |
| `NOTIFICATION_TEMPLATES_FILE` | `config/notification_templates.yaml` | wording |
| `NOTIFICATION_RECIPIENTS_FILE` | `config/notification_recipients.yaml` | distribution lists, one file per environment |
| `NOTIFICATION_MAX_ATTEMPTS` | `3` | per recipient, transient failures only |
| `NOTIFICATION_BACKOFF_SECONDS` | `2` | doubles each retry |
| `NOTIFICATION_TIMEOUT_SECONDS` | `10` | per provider HTTP call |
| `EMAIL_PROVIDER` / `EMAIL_API_KEY` / `EMAIL_FROM_ADDRESS` | empty | `sendgrid`, API key, verified sender |
| `SMS_PROVIDER` / `SMS_ACCOUNT_SID` / `SMS_API_KEY` / `SMS_SENDER_ID` | empty | `twilio`, account SID, auth token, From number |

## 10. Known limits

- Provider delivery receipts (SendGrid event webhook, Twilio status callback) are not consumed yet. `NOTIFIED` means "accepted by the provider", and the stored `provider_ref` is what a webhook handler would match on. This would be a natural Part 16/18 addition once the API has a public URL.
- There is no manual "retry this channel" action. The official can see `FAILED` and intervene through another channel, as the plan intends. A re-send endpoint can come later with Part 13 if the UI wants one.
- One worker thread delivers alerts one after another. At this scale that is fine, but a burst of alerts with many slow recipients would queue up.
