"""Alert lifecycle (Part 07 §3.4, Part 08 §2.4): DRAFT → READY → ISSUED, one record.

    DRAFT ──► READY ──► ISSUED   (DRAFT ──► ISSUED directly is allowed: "Issue Warning")
      ◄────────┘
    ISSUED is terminal and immutable: a wrong warning is corrected by a new alert.

Issuing dispatches every selected channel through the Notifier and records each result.
A failed channel is stored as FAILED with its reason; the alert is still ISSUED (the
decision to warn was made), and the response says which channels did not go out.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from heatwave_api.catalog import Catalog
from heatwave_api.errors import BadRequest, Conflict, NotFound, UnknownRegion
from heatwave_api.notifier import Notifier
from heatwave_api.repositories import Repository
from heatwave_api.schemas import (
    AlertCreate,
    AlertOut,
    AlertUpdate,
    ChannelDelivery,
    DeliverySummary,
    RegionOut,
)

log = logging.getLogger("heatwave_api.alerts")

TRANSITIONS = {
    "DRAFT": {"DRAFT", "READY", "ISSUED"},
    "READY": {"READY", "DRAFT", "ISSUED"},
    "ISSUED": {"ISSUED"},
}


def summarize(channels: list[ChannelDelivery]) -> DeliverySummary:
    count = lambda status: sum(c.status == status for c in channels)  # noqa: E731
    return DeliverySummary(
        total=len(channels),
        notified=count("NOTIFIED"),
        failed=count("FAILED"),
        pending=count("PENDING"),
        all_delivered=all(c.status == "NOTIFIED" for c in channels),
    )


class AlertService:
    def __init__(
        self,
        repo: Repository,
        catalog: Catalog,
        notifier: Notifier,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.repo, self.catalog, self.notifier, self.clock = repo, catalog, notifier, clock

    # -- helpers ----------------------------------------------------------------------

    def _region(self, region_id: str) -> RegionOut:
        region = self.catalog.regions.get(region_id)
        if region is None:
            raise UnknownRegion(f"Unknown region '{region_id}'.")
        return RegionOut(**region.__dict__)

    def _check_channels(self, channels: list[str]) -> list[str]:
        unknown = [c for c in channels if c not in self.catalog.channels]
        if unknown:
            raise BadRequest(
                f"Unknown channel(s) {unknown}.", details={"valid": sorted(self.catalog.channels)}
            )
        return list(dict.fromkeys(channels))  # a channel listed twice is notified once

    def _deliveries(self, channels: list[str], status: str = "READY") -> list[ChannelDelivery]:
        now = self.clock()
        return [
            ChannelDelivery(
                channel=c, label=self.catalog.channels[c].label, status=status, updated_at=now
            )
            for c in channels
        ]

    def _with(self, alert: AlertOut, **changes) -> AlertOut:
        channels = changes.get("channels", alert.channels)
        return alert.model_copy(
            update={
                **changes,
                "delivery_summary": summarize(channels),
                "updated_at": self.clock(),
                "idempotent_replay": False,
            }
        )

    # -- operations -------------------------------------------------------------------

    def create(self, body: AlertCreate, user_id: str) -> AlertOut:
        key = (user_id, str(body.client_request_id))
        existing = self.repo.find_alert_by_request(*key)
        if existing is not None:
            # Same request id, different content, is a client bug, not a replay.
            if not self._same_request(existing, body):
                raise Conflict("This client_request_id was already used for a different alert.")
            return existing.model_copy(update={"idempotent_replay": True})

        region = self._region(body.region_id)
        channels = self._check_channels(body.channels)
        if body.prediction_id and self.repo.get_prediction(body.prediction_id) is None:
            raise BadRequest(f"Unknown prediction '{body.prediction_id}'.")

        now = self.clock()
        alert_id = f"HW-{now.year}-{self.repo.next_alert_sequence(now.year):04d}"
        deliveries = self._deliveries(channels)
        alert = AlertOut(
            alert_id=alert_id,
            status="DRAFT",
            severity=body.severity,
            region=region,
            message=body.message,
            prediction_id=body.prediction_id,
            channels=deliveries,
            delivery_summary=summarize(deliveries),
            created_at=now,
            created_by=user_id,
            issued_at=None,
            updated_at=now,
        )
        self.repo.save_alert(alert, key)
        if body.status != "DRAFT":
            alert = self._transition(alert, body.status)
        log.info(
            "alert created",
            extra={"alert_id": alert.alert_id, "status": alert.status, "severity": alert.severity},
        )
        return alert

    def update(self, alert_id: str, body: AlertUpdate) -> AlertOut:
        alert = self.get(alert_id)
        edits = body.model_dump(exclude_none=True, exclude={"status"})
        if alert.status == "ISSUED":
            raise Conflict(
                "This alert has been issued and cannot be changed. Create a new alert instead."
            )
        changes: dict = {}
        if "severity" in edits:
            changes["severity"] = edits["severity"]
        if "message" in edits:
            changes["message"] = edits["message"]
        if "channels" in edits:
            changes["channels"] = self._deliveries(self._check_channels(edits["channels"]))
        if changes:
            alert = self._with(alert, **changes)
        if body.status is not None and body.status != alert.status:
            alert = self._transition(alert, body.status)
        else:
            self.repo.save_alert(alert)
        return alert

    def _transition(self, alert: AlertOut, target: str) -> AlertOut:
        if target not in TRANSITIONS[alert.status]:
            raise Conflict(f"An alert cannot go from {alert.status} to {target}.")
        if target != "ISSUED":
            alert = self._with(alert, status=target)
            self.repo.save_alert(alert)
            return alert
        return self._issue(alert)

    def _issue(self, alert: AlertOut) -> AlertOut:
        # Persist ISSUED with every channel PENDING *before* dispatching, so a crash
        # mid-dispatch leaves a truthful record rather than an alert that looks unsent.
        pending = self._deliveries([c.channel for c in alert.channels], "PENDING")
        alert = self._with(alert, status="ISSUED", issued_at=self.clock(), channels=pending)
        self.repo.save_alert(alert)

        results: list[ChannelDelivery] = []
        for delivery in alert.channels:
            try:
                outcome = self.notifier.send(alert, delivery.channel)
                status, detail = outcome.status, outcome.detail
            except Exception:  # a notifier bug must not abort the other channels
                log.exception("notifier raised", extra={"alert_id": alert.alert_id})
                status, detail = "FAILED", "The notification service reported an internal error."
            if status == "FAILED":
                log.warning(
                    "channel delivery failed",
                    extra={"alert_id": alert.alert_id, "channel": delivery.channel},
                )
            results.append(
                delivery.model_copy(
                    update={"status": status, "detail": detail, "updated_at": self.clock()}
                )
            )
        alert = self._with(alert, channels=results)
        self.repo.save_alert(alert)
        return alert

    def get(self, alert_id: str) -> AlertOut:
        alert = self.repo.get_alert(alert_id)
        if alert is None:
            raise NotFound(f"Alert '{alert_id}' does not exist.")
        return alert

    @staticmethod
    def _same_request(existing: AlertOut, body: AlertCreate) -> bool:
        return (
            existing.region.id == body.region_id
            and existing.severity == body.severity
            and existing.message == body.message
            and sorted(c.channel for c in existing.channels) == sorted(set(body.channels))
        )
