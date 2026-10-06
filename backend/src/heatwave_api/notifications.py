"""The boundary to the notification service (Part 09).

Part 07 owns *when* a dispatch happens (an alert reaching ISSUED) and that every
channel's outcome is recorded, one channel at a time, so a failure on one channel
never hides behind a success on another. Part 09 owns *how* a channel is delivered:
providers, templates, recipients, retries and asynchronous dispatch. Until then,
NOTIFICATIONS_MODE=mock logs instead of sending, and can be told to fail chosen
channels so the partial-failure path can be exercised end to end.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    error: str | None = None


class Notifier(Protocol):
    mode: str

    def send(self, alert: dict, channel: str) -> DeliveryResult:
        """Deliver one issued alert to one channel. May raise; the caller records it."""
        ...


class MockNotifier:
    mode = "mock"

    def __init__(self, fail_channels: list[str] | None = None):
        self.fail_channels = set(fail_channels or ())

    def send(self, alert: dict, channel: str) -> DeliveryResult:
        if channel in self.fail_channels:
            log.warning("mock delivery failed", extra={"alert": alert["code"], "channel": channel})
            return DeliveryResult(False, "Mock mode: this channel is configured to fail")
        log.info("mock delivery", extra={"alert": alert["code"], "channel": channel})
        return DeliveryResult(True)
