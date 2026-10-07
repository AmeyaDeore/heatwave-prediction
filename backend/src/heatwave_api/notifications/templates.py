"""Message templates (Part 09 §4): wording lives in config/notification_templates.yaml.

`Templates.render(mechanism, alert)` turns an alert into the text one mechanism sends.
Nothing here knows how a message is delivered, and the dispatch code holds no wording.
"""

from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path
from string import Template

import yaml

from heatwave_api.schemas import AlertOut

IST = timezone(timedelta(hours=5, minutes=30), "IST")
ELLIPSIS = "..."  # ASCII on purpose: keeps an SMS in the GSM-7 alphabet
FIELDS = ("severity_label", "region_name", "district", "state", "message", "alert_id", "issued_at")


@dataclass(frozen=True)
class Message:
    body: str
    subject: str | None = None  # email subject / in-app title


def _shorten(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` characters at a word boundary, ending in '...'."""
    if len(text) <= limit:
        return text
    if limit <= len(ELLIPSIS):
        return text[: max(limit, 0)]
    cut = text[: limit - len(ELLIPSIS)]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:-") + ELLIPSIS


class Templates:
    def __init__(self, spec: dict):
        self.version = spec["version"]
        self.severity_labels = spec["severity_labels"]
        self._email = (Template(spec["email"]["subject"]), Template(spec["email"]["body"]))
        self._sms = Template(spec["sms"]["body"])
        self.sms_max_chars = int(spec["sms"]["max_chars"])
        self._in_app = (Template(spec["in_app"]["title"]), Template(spec["in_app"]["body"]))
        self._check()

    @classmethod
    def load(cls, path: Path) -> "Templates":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    def _check(self) -> None:
        """Fail at startup on a placeholder typo, not on the first real alert."""
        probe = dict.fromkeys(FIELDS, "x")
        for t in (*self._email, self._sms, *self._in_app):
            t.substitute(probe)
        if self.sms_max_chars < 40:
            raise ValueError("notification_templates.yaml: sms.max_chars is unreasonably small")

    def _fields(self, alert: AlertOut) -> dict[str, str]:
        issued = alert.issued_at or alert.updated_at
        return {
            "severity_label": self.severity_labels[alert.severity],
            "region_name": alert.region.name,
            "district": alert.region.district,
            "state": alert.region.state,
            "message": " ".join(alert.message.split()),
            "alert_id": alert.alert_id,
            "issued_at": issued.astimezone(IST).strftime("%d %b %Y, %H:%M IST"),
        }

    def render(self, mechanism: str, alert: AlertOut) -> Message:
        fields = self._fields(alert)
        if mechanism == "email":
            subject, body = self._email
            return Message(body.substitute(fields), subject.substitute(fields))
        if mechanism == "in_app":
            title, body = self._in_app
            return Message(body.substitute(fields), title.substitute(fields))
        if mechanism == "sms":
            return Message(self.render_sms(fields))
        raise ValueError(f"No template for mechanism '{mechanism}'")

    def render_sms(self, fields: dict[str, str]) -> str:
        """Shorten only the advisory text, so severity, region and reference survive."""
        full = self._sms.substitute(fields)
        if len(full) <= self.sms_max_chars:
            return full
        frame = len(self._sms.substitute({**fields, "message": ""}))
        room = self.sms_max_chars - frame
        if room >= len(ELLIPSIS) + 10:
            return self._sms.substitute({**fields, "message": _shorten(fields["message"], room)})
        return _shorten(full, self.sms_max_chars)  # template itself too long: last resort
