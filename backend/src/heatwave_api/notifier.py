"""The seam to the notification service (Part 09).

`Notifier.send` delivers one alert on one channel and reports the outcome. It must not
raise for a delivery failure: it returns FAILED with a reason, and the alert service
records that per channel, so one dead channel never hides behind an overall "success".

The implementation is `notifications.service.NotificationService`; NOTIFICATIONS_MODE
chooses mock or live providers inside it. Tests pass their own `Notifier`.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from heatwave_api.schemas import AlertOut


@dataclass(frozen=True)
class DeliveryResult:
    status: Literal["NOTIFIED", "PENDING", "FAILED"]
    detail: str | None = None


class Notifier(Protocol):
    def send(self, alert: AlertOut, channel_id: str) -> DeliveryResult: ...
