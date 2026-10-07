"""Distribution lists (Part 09 §5 step 2): who receives a channel for a region.

Read from NOTIFICATION_RECIPIENTS_FILE, so every environment has its own list and a
test run can never pick up a real emergency-services roster by accident.
"""

import re
from pathlib import Path

import yaml

E164 = re.compile(r"^\+[1-9]\d{6,14}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Recipients:
    def __init__(self, spec: dict, mechanisms: dict[str, str]):
        """`mechanisms` maps channel id -> sms | email | in_app (config/alert_channels.yaml)."""
        self._lists: dict[str, dict] = {}
        for channel, entry in (spec.get("channels") or {}).items():
            mechanism = mechanisms.get(channel)
            if mechanism is None:
                raise ValueError(f"notification recipients: unknown channel '{channel}'")
            if mechanism == "in_app":
                raise ValueError(f"notification recipients: '{channel}' is in_app, it has none")
            pattern = E164 if mechanism == "sms" else EMAIL
            lists = [entry.get("default") or [], *(entry.get("regions") or {}).values()]
            bad = [r for group in lists for r in group if not pattern.match(str(r))]
            if bad:
                raise ValueError(
                    f"notification recipients: invalid {mechanism} for '{channel}': {bad}"
                )
            self._lists[channel] = entry

    @classmethod
    def load(cls, path: Path, mechanisms: dict[str, str]) -> "Recipients":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, mechanisms)

    def resolve(self, channel: str, region_id: str) -> list[str]:
        """The region's own list if it has one, else the channel default; de-duplicated."""
        entry = self._lists.get(channel) or {}
        found = (entry.get("regions") or {}).get(region_id) or entry.get("default") or []
        return list(dict.fromkeys(str(r) for r in found))
