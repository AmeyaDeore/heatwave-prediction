# Log 09: Notification service

| | |
|---|---|
| Plan | [Implementation/09-notification-service.md](../../Implementation/09-notification-service.md) |
| Status | Complete against the plan's checklist. Delivery-receipt webhooks are deferred (open items) |
| Date | 2026-10-07 |
| Branch / commits | `part-07/backend-api`, one commit on top of `4647122` |
| Tests | 36 new in `backend/tests/test_notifications.py`. 133 backend, 289 total passing |

## Summary

Part 09 replaced the `MockNotifier` seam with a real notification service. Issuing an alert now stores every channel as PENDING and returns. A background worker then delivers each channel through its mechanism: SMS (Twilio), email (SendGrid), or an in-app public advisory that the portal and display boards poll. The worker writes each outcome to `alert_channel_deliveries` as it lands. Transient provider failures are retried with backoff, while permanent ones fail at once. Every attempt goes to an append-only audit table and the JSON log. Mock mode is the default and sends nothing, so development never reaches real people or uses provider credit. The whole flow was run on the real production model against `data/local/heatwave.db`.

## What was built

| Path | Role |
|---|---|
| `backend/src/heatwave_api/notifications/templates.py` | Loads `config/notification_templates.yaml`, renders email/SMS/in-app, applies the SMS 160-character GSM-7 rule (shortens only the advisory text), checks placeholders at startup |
| `notifications/recipients.py` | Per-channel and per-region distribution lists, with E.164/email validation; a region list overrides the default |
| `notifications/providers.py` | `SendGridEmail`, `TwilioSms` (stdlib `urllib`, explicit timeout), `MockProvider` (outbox and simulated failures), and `TransientError` / `PermanentError` classification of HTTP outcomes |
| `notifications/service.py` | `NotificationService` (implements `Notifier`): mechanism routing, per-recipient retry policy, `_Audit` writes attempts to the store and the log, `build_providers` (mock/live and the credential checks) |
| `notifications/dispatch.py` | `BackgroundDispatcher` (one worker thread, queue, `join`, graceful `stop`) and `InlineDispatcher` |
| `db/migrations/0002_notifications.sql` | `notification_attempts` (append-only triggers, FK to the delivery row) and `public_advisories` (unique per alert and channel) |
| `alerts.py` | `_issue` saves PENDING then submits. `deliver(alert_id)` is the job (only PENDING channels, each written immediately). `resume_pending()` runs at startup |
| `repositories.py`, `db/repository.py` | `update_delivery`, `alerts_with_pending_deliveries`, `record_attempt`, `list_attempts`, `publish_advisory`, `list_advisories` (SQLite and in-memory) |
| `routes.py`, `schemas.py` | `GET /alerts/{id}/attempts` (protected), `GET /advisories` (public), and `mechanism` on `GET /alert-channels` |
| `app.py` | Builds `NotificationService` by default, picks the dispatch mode, resumes PENDING at startup, drains the queue on shutdown |
| `catalog.py` | `Channel.mechanism`, validated |
| `config/alert_channels.yaml`, `config/notification_templates.yaml`, `config/notification_recipients.yaml` | Mapping, wording, and the development recipient list |
| `docs/notifications/README.md`, `docs/decisions/0008-notification-service.md` | Service documentation and ADR |

**Contract changes others rely on:** schema version **2**. `POST`/`PATCH ... ISSUED` normally returns channels `PENDING`, so the UI must poll. `ChannelOut` gains `mechanism`. There are two new endpoints. New env vars: `NOTIFICATIONS_DISPATCH`, `NOTIFICATION_TEMPLATES_FILE`, `NOTIFICATION_RECIPIENTS_FILE`, `NOTIFICATION_MAX_ATTEMPTS`, `NOTIFICATION_BACKOFF_SECONDS`, `NOTIFICATION_TIMEOUT_SECONDS`, `SMS_ACCOUNT_SID`. `EMAIL_PROVIDER`/`SMS_PROVIDER` are now restricted to `sendgrid`/`twilio`.
**Dependency change:** none. The providers use the standard library, deliberately not the vendor SDKs.
**Docs updated:** `docs/api/README.md` (issuing, the two new endpoints, the channel list, limits), `docs/database/README.md` (ER diagram, the two tables), ADR 0006/0007 notes, `config/README.md`, `docs/configuration-and-secrets.md`, `docs/local-dev-runbook.md`, `docs/README.md`, `backend/README.md`, `backend/.env.example`, and the Part 09 plan checklist.

## Key decisions and why

The full table is in [ADR 0008](../decisions/0008-notification-service.md). The main points:

- **Background dispatch with polling.** "Issue Warning" must not wait about 30 s for a slow SMS gateway. One worker thread is proportionate to the scale. Polling `GET /alerts/{id}` matches the rest of the read model, and push would add complexity for nothing.
- **At-least-once delivery.** PENDING is committed before queueing and resumed on startup. A crash can repeat an SMS but cannot lose a warning. Advisories cannot duplicate.
- **Retry per recipient, not per channel.** Retrying a whole channel would re-send to recipients who already received the message.
- **A channel is NOTIFIED only if every recipient got it.** Otherwise it is FAILED with "k of n failed". A partly delivered warning must not look complete to the official.
- **Safety by construction.** The committed recipients are `.invalid` addresses and Twilio magic numbers (asserted by a test), `live` refuses `APP_ENV=test`, and missing credentials stop startup.
- **SMS stays ASCII.** One em dash would switch the message to UCS-2 and cut a segment to 70 characters. The templates use `-` and `...` for this reason.

## Verification

```
uv run ruff format backend && uv run ruff check backend      -> All checks passed
cd backend && uv run pytest -q tests/test_notifications.py   -> 36 passed
uv run pytest -q   (repo root, ml + backend)                 -> 289 passed in 166s
uv run pre-commit run --all-files                            -> all hooks Passed
```

End to end on the real production model (`xgboost-20260928T100821Z-0bde51`), local DB, `NOTIFICATIONS_MODE=mock`, background dispatch. The DB was backed up first (`heatwave-db backup` → `data/local/backups/heatwave-20261007T101902Z.db`), and migration 0002 was then applied automatically:

```
POST 201 HW-2026-0001 ['PENDING', 'PENDING', 'PENDING', 'PENDING', 'PENDING']
  public_mobile NOTIFIED | sent to 1 recipient via mock-sms
  government_portal NOTIFIED | published as a public advisory
  display_boards NOTIFIED | published as a public advisory
  emergency_services NOTIFIED | sent to 1 recipient via mock-sms
  hospitals NOTIFIED | sent to 2 recipients via mock-email
summary {'total': 5, 'notified': 5, 'failed': 0, 'pending': 0, 'all_delivered': True}
attempts 6 {'SUCCESS'}
sms 158 'SEVERE HEATWAVE ALERT - Mumbai: Severe heatwave expected. Avoid prolonged outdoor exposure between 12 PM and 4 PM, stay hydrated, check on... Ref HW-2026-0001'
heatwave-db status -> version: 2, notification_attempts 6, public_advisories 2
```

The tests cover: the channel mapping; template rendering and SMS truncation; placeholder typos; recipient resolution and validation; the committed list being test-only; success with auditing; transient retry with 2 s/4 s backoff; giving up after 3 attempts; permanent failures not retried; unexpected errors not leaked; partial-recipient failure; no recipients; idempotent advisories; HTTP classification (503/429/400/401/timeout/URL error); the Twilio and SendGrid request shapes; mock/live provider building; background PENDING → NOTIFIED; a slow channel not blocking the response; startup resume of stranded PENDING; append-only triggers; and the audit endpoint's auth and 404.

## Deviations and issues found

- **The response now normally shows PENDING.** Part 07's contract implied final statuses in the `POST` response. That is still true with `NOTIFICATIONS_DISPATCH=inline`, which the existing alert tests use (`conftest.py`), so all 97 earlier tests pass unchanged apart from the schema-version assertions.
- **`test_database.py`** asserted schema version 1. It now asserts 2 (0001 + 0002).
- **Unexpected provider exceptions are treated as transient** (retried), but the stored detail is generic, so internals never reach the UI.
- **TestClient already has an `.auth` attribute.** The new tests use `.bearer` for headers. This affected tests only.

## Open items

- Consume delivery receipts (SendGrid event webhook, Twilio status callback) keyed on the stored `provider_ref`. This needs a public URL, so it belongs to Parts 16/18. Until then, `NOTIFIED` means "accepted by the provider".
- **Part 13:** poll `GET /alerts/{id}` while `delivery_summary.pending > 0`. Show per-channel `detail` for FAILED, and optionally show the audit trail. A manual "re-send channel" action is not built and can be added if the UI wants one.
- **Part 18:** provide a per-environment `NOTIFICATION_RECIPIENTS_FILE` (uncommitted) and the provider credentials. Back up before migrating to schema version 2.
- **Scale:** at more than one API process, move the job (an alert id) to a real queue (docs/notifications §8).

## Handoff

> Providers configured: SendGrid (email), Twilio (SMS) (mock mode available via: `NOTIFICATIONS_MODE=mock`, the default). Channel mapping: public_mobile and emergency_services → SMS, hospitals → email, government_portal and display_boards → in-app advisory (`GET /api/v1/advisories`). Dispatch is async (one background worker, PENDING resumed on restart); status refresh approach: the frontend polls `GET /api/v1/alerts/{id}` while `delivery_summary.pending > 0`. Part 13 (Alert Management UI) can now build against real per-channel status values from the database, plus the audit trail at `GET /api/v1/alerts/{id}/attempts`.
