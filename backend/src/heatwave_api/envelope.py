"""One response shape for every endpoint (Part 07 §4), so the frontend handles errors once.

success: {"status": "ok",    "data": {...},  "meta": {"request_id": "..."}}
failure: {"status": "error", "error": {"kind", "code", "message", "details"}, "meta": {...}}
"""

from typing import Literal

from pydantic import BaseModel


class Meta(BaseModel):
    request_id: str
    api_version: str = "v1"


class Envelope[T](BaseModel):
    status: Literal["ok"] = "ok"
    data: T
    meta: Meta


class ErrorBody(BaseModel):
    kind: Literal["client", "upstream", "internal"]
    code: str
    message: str
    details: dict | list | None = None


class ErrorEnvelope(BaseModel):
    status: Literal["error"] = "error"
    error: ErrorBody
    meta: Meta
