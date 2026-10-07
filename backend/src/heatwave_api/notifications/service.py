"""The notification service (Part 09): one alert, one channel -> a recorded outcome.

`NotificationService.send(alert, channel)` implements the `Notifier` seam:

  1. look up the channel's mechanism (config/alert_channels.yaml)
  2. in_app: publish a public advisory (idempotent per alert+channel); no external call
     sms/email: render the template, resolve the region's recipients, and send to each
     recipient through the provider, retrying transient failures with backoff
  3. write every attempt to the audit trail (notification_attempts) and the log
  4. return NOTIFIED only if every recipient got it; otherwise FAILED with a reason
     that says how many recipients failed and why

It never raises for a delivery problem. The caller (AlertService) writes the result to
alert_channel_deliveries, which is what the Alert Management page shows.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from heatwave_api.catalog import Catalog
from heatwave_api.config import Settings
from heatwave_api.notifications.providers import (
    MockProvider,
    PermanentError,
    Provider,
    SendGridEmail,
    TransientError,
    TwilioSms,
)
from heatwave_api.notifications.recipients import Recipients
from heatwave_api.notifications.templates import Message, Templates
from heatwave_api.notifier import DeliveryResult
from heatwave_api.schemas import AdvisoryOut, AlertOut

log = logging.getLogger("heatwave_api.notifications")


@dataclass(frozen=True)
class Attempt:
    alert_id: str
    channel: str
    mechanism: str
    provider: str
    recipient: str | None
    attempt: int
    outcome: str  # SUCCESS | TRANSIENT_FAILURE | PERMANENT_FAILURE
    detail: str | None
    provider_ref: str | None
    started_at: datetime
    duration_ms: int


class NotificationStore(Protocol):
    """Where the service records what it did (SqliteRepository / MemoryRepository)."""

    def record_attempt(self, attempt: Attempt) -> None: ...

    def publish_advisory(self, advisory: AdvisoryOut) -> None: ...


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 2.0  # wait before retry n is backoff * 2**(n-1)

    def delay(self, attempt: int) -> float:
        return self.backoff_seconds * 2 ** (attempt - 1)


class ConfigurationError(RuntimeError):
    pass


def build_providers(settings: Settings) -> dict[str, Provider]:
    """mock: nothing leaves the process. live: the configured providers, all credentials set."""
    if settings.notifications_mode == "mock":
        return {"sms": MockProvider("sms"), "email": MockProvider("email")}
    if settings.app_env == "test":
        raise ConfigurationError("NOTIFICATIONS_MODE=live is refused when APP_ENV=test.")
    missing = [
        name
        for name, value in {
            "EMAIL_PROVIDER": settings.email_provider,
            "EMAIL_API_KEY": settings.email_api_key.get_secret_value(),
            "EMAIL_FROM_ADDRESS": settings.email_from_address,
            "SMS_PROVIDER": settings.sms_provider,
            "SMS_ACCOUNT_SID": settings.sms_account_sid,
            "SMS_API_KEY": settings.sms_api_key.get_secret_value(),
            "SMS_SENDER_ID": settings.sms_sender_id,
        }.items()
        if not value
    ]
    if missing:
        raise ConfigurationError(f"NOTIFICATIONS_MODE=live needs {', '.join(missing)}.")
    timeout = settings.notification_timeout_seconds
    return {
        "email": SendGridEmail(
            settings.email_api_key.get_secret_value(), settings.email_from_address, timeout
        ),
        "sms": TwilioSms(
            settings.sms_account_sid,
            settings.sms_api_key.get_secret_value(),
            settings.sms_sender_id,
            timeout,
        ),
    }


class NotificationService:
    def __init__(
        self,
        catalog: Catalog,
        templates: Templates,
        recipients: Recipients,
        providers: dict[str, Provider],
        store: NotificationStore,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.catalog, self.templates, self.recipients = catalog, templates, recipients
        self.providers, self.store = providers, store
        self.policy = policy or RetryPolicy()
        self.sleep, self.clock = sleep, clock

    @classmethod
    def from_settings(
        cls, settings: Settings, catalog: Catalog, store: NotificationStore
    ) -> "NotificationService":
        mechanisms = {c.id: c.mechanism for c in catalog.channels.values()}
        return cls(
            catalog,
            Templates.load(settings.notification_templates_file),
            Recipients.load(settings.notification_recipients_file, mechanisms),
            build_providers(settings),
            store,
            RetryPolicy(settings.notification_max_attempts, settings.notification_backoff_seconds),
        )

    # -- Notifier ---------------------------------------------------------------------

    def send(self, alert: AlertOut, channel_id: str) -> DeliveryResult:
        mechanism = self.catalog.channels[channel_id].mechanism
        if mechanism == "in_app":
            return self._publish(alert, channel_id)
        return self._deliver_external(alert, channel_id, mechanism)

    # -- in_app -----------------------------------------------------------------------

    def _publish(self, alert: AlertOut, channel: str) -> DeliveryResult:
        audit = _Audit(self, alert, channel, "in_app", "in_app")
        message = self.templates.render("in_app", alert)
        try:
            self.store.publish_advisory(
                AdvisoryOut(
                    alert_id=alert.alert_id,
                    channel=channel,
                    region_id=alert.region.id,
                    severity=alert.severity,
                    title=message.subject or "",
                    body=message.body,
                    published_at=self.clock(),
                )
            )
        except Exception:
            log.exception("advisory publish failed", extra={"alert_id": alert.alert_id})
            detail = "could not publish the advisory"
            audit.record(None, 1, "PERMANENT_FAILURE", detail)
            return DeliveryResult("FAILED", detail)
        audit.record(None, 1, "SUCCESS")
        return DeliveryResult("NOTIFIED", "published as a public advisory")

    # -- sms / email ------------------------------------------------------------------

    def _deliver_external(self, alert: AlertOut, channel: str, mechanism: str) -> DeliveryResult:
        recipients = self.recipients.resolve(channel, alert.region.id)
        if not recipients:
            detail = f"no {mechanism} recipients configured for {alert.region.id}"
            _Audit(self, alert, channel, mechanism, "none").record(
                None, 1, "PERMANENT_FAILURE", detail
            )
            return DeliveryResult("FAILED", detail)

        message = self.templates.render(mechanism, alert)
        provider = self.providers[mechanism]
        audit = _Audit(self, alert, channel, mechanism, provider.name)
        failures = []
        for recipient in recipients:
            error = self._send_with_retry(audit, provider, recipient, message)
            if error:
                failures.append(error)
        if not failures:
            n = len(recipients)
            return DeliveryResult(
                "NOTIFIED", f"sent to {n} recipient{'s' * (n != 1)} via {provider.name}"
            )
        return DeliveryResult(
            "FAILED",
            f"{len(failures)} of {len(recipients)} {mechanism} recipients failed: {failures[0]}",
        )

    def _send_with_retry(
        self, audit: "_Audit", provider: Provider, recipient: str, message: Message
    ) -> str | None:
        """None when delivered, else the last error (safe to store and show).

        Transient failures are retried up to max_attempts with doubling backoff; a
        permanent failure stops at once, since repeating it cannot help.
        """
        for attempt in range(1, self.policy.max_attempts + 1):
            audit.start()
            try:
                ref = provider.send(recipient, message)
            except PermanentError as e:
                audit.record(recipient, attempt, "PERMANENT_FAILURE", str(e))
                return str(e)
            except Exception as e:  # TransientError, or a provider bug: worth another try
                if isinstance(e, TransientError):
                    detail = str(e)
                else:
                    log.exception("provider raised", extra={"alert_id": audit.alert.alert_id})
                    detail = "unexpected provider error"
                audit.record(recipient, attempt, "TRANSIENT_FAILURE", detail)
                if attempt == self.policy.max_attempts:
                    return f"{detail} (gave up after {attempt} attempts)"
                self.sleep(self.policy.delay(attempt))
            else:
                audit.record(recipient, attempt, "SUCCESS", ref=ref)
                return None
        raise AssertionError("unreachable: max_attempts >= 1")


class _Audit:
    """Writes attempts for one (alert, channel, provider) to the store and the log."""

    def __init__(self, service, alert: AlertOut, channel: str, mechanism: str, provider: str):
        self.service, self.alert = service, alert
        self.channel, self.mechanism, self.provider = channel, mechanism, provider
        self.start()

    def start(self) -> None:
        self.started, self._t0 = self.service.clock(), time.perf_counter()

    def record(
        self,
        recipient: str | None,
        attempt: int,
        outcome: str,
        detail: str | None = None,
        ref: str | None = None,
    ) -> None:
        entry = Attempt(
            alert_id=self.alert.alert_id,
            channel=self.channel,
            mechanism=self.mechanism,
            provider=self.provider,
            recipient=recipient,
            attempt=attempt,
            outcome=outcome,
            detail=detail,
            provider_ref=ref,
            started_at=self.started,
            duration_ms=max(0, round((time.perf_counter() - self._t0) * 1000)),
        )
        level = logging.INFO if outcome == "SUCCESS" else logging.WARNING
        fields = {k: v for k, v in entry.__dict__.items() if k != "started_at"}
        log.log(level, "notification attempt", extra=fields)
        try:
            self.service.store.record_attempt(entry)
        except Exception:  # the log line above is the fallback record; never block delivery
            log.exception("could not store notification attempt", extra=fields)
