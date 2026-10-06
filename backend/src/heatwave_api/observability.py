"""Structured JSON logs, one line per event, with the request id on every line.

Each request logs one ``request`` event: method, path, status, latency, client,
request id, and for predictions the region, risk class and model version (Part 07
§7). Headers and bodies are never logged, so tokens and passwords cannot leak into
the logs (Part 15 §7).
"""

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# Attributes every LogRecord has; anything else was passed with extra= and is logged.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


def request_id_from(header: str | None) -> str:
    """The caller's X-Request-ID if it is a sane token, else a new one."""
    if header and _REQUEST_ID.match(header):
        return header
    return uuid.uuid4().hex


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        entry |= {k: v for k, v in vars(record).items() if k not in _STANDARD}
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Uvicorn's access log would duplicate our request event, without the request id.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
