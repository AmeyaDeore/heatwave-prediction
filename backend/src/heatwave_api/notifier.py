"""The seam to the notification service (Part 09).

`Notifier.send` delivers one alert on one channel and reports the outcome. It must not
raise for a delivery failure: it returns FAILED with a reason, and the alert service
records that per channel, so one dead channel never hides behind an overall "success".
"""

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from heatwave_api.schemas import AlertOut

log = logging.getLogger("heatwave_api.notifier")


@dataclass(frozen=True)
class DeliveryResult:
    status: Literal["NOTIFIED", "PENDING", "FAILED"]
    detail: str | None = None


class Notifier(Protocol):
    def send(self, alert: AlertOut, channel_id: str) -> DeliveryResult: ...


class MockNotifier:
    """NOTIFICATIONS_MODE=mock: logs the dispatch, sends nothing."""

    def send(self, alert: AlertOut, channel_id: str) -> DeliveryResult:
        log.info(
            "mock notification",
            extra={"alert_id": alert.alert_id, "channel": channel_id, "severity": alert.severity},
        )
        return DeliveryResult("NOTIFIED", "mock mode: logged, not sent")
