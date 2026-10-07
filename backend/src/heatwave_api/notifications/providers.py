"""External delivery providers (Part 09 §3): SendGrid for email, Twilio for SMS, plus mocks.

A provider sends one message to one recipient and either returns a provider reference or
raises. The exception type is the retry decision:

  TransientError  worth retrying: timeout, connection error, HTTP 429 or 5xx
  PermanentError  retrying cannot help: bad credentials, invalid recipient, other 4xx

Calls use the standard library's urllib with an explicit timeout, so a hung provider
costs at most NOTIFICATION_TIMEOUT_SECONDS per attempt, never an indefinite wait.
"""

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from heatwave_api.notifications.templates import Message

log = logging.getLogger("heatwave_api.notifications")


class DeliveryError(Exception):
    """Base class. `str(error)` is safe to store and show: no secrets, no message body."""


class TransientError(DeliveryError):
    pass


class PermanentError(DeliveryError):
    pass


class Provider(Protocol):
    name: str

    def send(self, recipient: str, message: Message) -> str | None: ...


def _post(
    url: str, data: bytes, headers: dict[str, str], timeout: float
) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https URLs)
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:500].decode("utf-8", "replace")
        if e.code == 429 or e.code >= 500:
            raise TransientError(f"provider returned HTTP {e.code}") from e
        raise PermanentError(f"provider rejected the message (HTTP {e.code}): {body}") from e
    except TimeoutError as e:
        raise TransientError(f"provider did not answer within {timeout:g}s") from e
    except urllib.error.URLError as e:
        raise TransientError(f"could not reach provider: {e.reason}") from e


class SendGridEmail:
    """SendGrid v3 Mail Send. Free tier, 202 Accepted + X-Message-Id for event webhooks."""

    name = "sendgrid"
    url = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self, api_key: str, from_address: str, timeout: float):
        self._key, self.from_address, self.timeout = api_key, from_address, timeout

    def send(self, recipient: str, message: Message) -> str | None:
        payload = {
            "personalizations": [{"to": [{"email": recipient}]}],
            "from": {"email": self.from_address},
            "subject": message.subject or "",
            "content": [{"type": "text/plain", "value": message.body}],
        }
        _, headers, _ = _post(
            self.url,
            json.dumps(payload).encode(),
            {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            self.timeout,
        )
        return headers.get("X-Message-Id") or headers.get("x-message-id")


class TwilioSms:
    """Twilio Programmable Messaging. Trial account; the response's `sid` tracks delivery."""

    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, sender: str, timeout: float):
        self.url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        token = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        self._auth, self.sender, self.timeout = f"Basic {token}", sender, timeout

    def send(self, recipient: str, message: Message) -> str | None:
        data = urllib.parse.urlencode({"To": recipient, "From": self.sender, "Body": message.body})
        _, _, body = _post(
            self.url,
            data.encode(),
            {"Authorization": self._auth, "Content-Type": "application/x-www-form-urlencoded"},
            self.timeout,
        )
        return json.loads(body or b"{}").get("sid")


class MockProvider:
    """NOTIFICATIONS_MODE=mock: logs the message and keeps it in `outbox`; sends nothing.

    Recipients ending in `.fail` / `.retry` (or numbers ending 0000 / 9999) simulate a
    permanent / transient provider failure, so the retry and FAILED paths can be
    demonstrated locally without a provider account.
    """

    def __init__(self, mechanism: str):
        self.name = f"mock-{mechanism}"
        self.outbox: list[tuple[str, Message]] = []

    def send(self, recipient: str, message: Message) -> str | None:
        if recipient.endswith((".fail", "0000")):
            raise PermanentError("mock: recipient rejected")
        if recipient.endswith((".retry", "9999")):
            raise TransientError("mock: provider temporarily unavailable")
        self.outbox.append((recipient, message))
        log.info("mock notification", extra={"provider": self.name, "recipient": recipient})
        return f"{self.name}-{len(self.outbox)}"
