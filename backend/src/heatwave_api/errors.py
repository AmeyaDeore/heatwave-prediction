"""The error taxonomy (Part 07 §6): every failure is one of three kinds.

| kind     | meaning                                    | HTTP        |
|----------|--------------------------------------------|-------------|
| client   | the caller sent something wrong            | 4xx         |
| upstream | a data source we depend on is unusable     | 502 / 503   |
| internal | our own model, explainer or code failed    | 500 / 503   |

Messages are written for the caller and never carry stack traces or paths. The full
detail goes to the log, tagged with the same ``request_id`` the response returns.
"""

from typing import Literal

ErrorKind = Literal["client", "upstream", "internal"]


class ApiError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    kind: ErrorKind = "internal"

    def __init__(
        self,
        message: str,
        *,
        details: dict | list | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers or {}


class BadRequest(ApiError):
    status_code, code, kind = 400, "BAD_REQUEST", "client"


class ValidationFailed(ApiError):
    status_code, code, kind = 422, "VALIDATION_ERROR", "client"


class Unauthorized(ApiError):
    status_code, code, kind = 401, "UNAUTHORIZED", "client"


class NotFound(ApiError):
    status_code, code, kind = 404, "NOT_FOUND", "client"


class UnknownRegion(NotFound):
    code = "UNKNOWN_REGION"


class Conflict(ApiError):
    status_code, code, kind = 409, "CONFLICT", "client"


class TooManyRequests(ApiError):
    status_code, code, kind = 429, "RATE_LIMITED", "client"


class UpstreamUnavailable(ApiError):
    """The weather data the pipeline ingests is missing, unreadable or lacks the request."""

    status_code, code, kind = 503, "WEATHER_DATA_UNAVAILABLE", "upstream"


class ModelUnavailable(ApiError):
    status_code, code, kind = 503, "MODEL_UNAVAILABLE", "internal"


class PredictionFailed(ApiError):
    status_code, code, kind = 500, "PREDICTION_FAILED", "internal"


class HttpFailure(ApiError):
    """An error whose status and code are decided at the point of use (framework errors)."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        kind: ErrorKind = "client",
        details: dict | list | None = None,
    ):
        super().__init__(message, details=details)
        self.status_code, self.code, self.kind = status_code, code, kind
