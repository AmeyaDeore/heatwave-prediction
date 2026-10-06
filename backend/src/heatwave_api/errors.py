"""The error taxonomy (Part 07 §6). Every failure the API reports is one of these.

Four categories, told apart in both the response body and the logs:

    client    the request is wrong: bad input, unknown id, conflict, rate limit    4xx
    auth      missing/invalid/expired token, bad credentials, not allowed          401/403
    upstream  the weather source failed; not our bug, retrying later may help      502/503
    internal  our model, explainer, database or code failed                        500/503

Messages are written for the caller and never carry a stack trace, a SQL statement
or a file path. The detail goes to the log, under the same request id.
"""

from typing import Any, Literal

Category = Literal["client", "auth", "upstream", "internal"]


class ApiError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    category: Category = "internal"

    def __init__(
        self,
        message: str,
        *,
        details: Any = None,
        headers: dict[str, str] | None = None,
        code: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers or {}
        if code:
            self.code = code


# -- client -----------------------------------------------------------------------------


class BadRequest(ApiError):
    status_code, code, category = 400, "BAD_REQUEST", "client"


class ValidationFailed(ApiError):
    status_code, code, category = 422, "VALIDATION_ERROR", "client"


class NotFound(ApiError):
    status_code, code, category = 404, "NOT_FOUND", "client"


class UnknownRegion(NotFound):
    code = "UNKNOWN_REGION"


class Conflict(ApiError):
    status_code, code, category = 409, "CONFLICT", "client"


class RateLimited(ApiError):
    status_code, code, category = 429, "RATE_LIMITED", "client"


# -- auth -------------------------------------------------------------------------------


class Unauthenticated(ApiError):
    status_code, code, category = 401, "UNAUTHENTICATED", "auth"

    def __init__(self, message: str = "Sign in to do this.", **kwargs):
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kwargs)


class Forbidden(ApiError):
    status_code, code, category = 403, "FORBIDDEN", "auth"


# -- upstream ---------------------------------------------------------------------------


class UpstreamUnavailable(ApiError):
    """The weather source could not be reached (after retries). Try again later."""

    status_code, code, category = 503, "WEATHER_SOURCE_UNAVAILABLE", "upstream"


class UpstreamBadResponse(ApiError):
    """The weather source answered, but with an error or data we cannot use."""

    status_code, code, category = 502, "WEATHER_SOURCE_ERROR", "upstream"


# -- internal ---------------------------------------------------------------------------


class InternalError(ApiError):
    status_code, code, category = 500, "INTERNAL_ERROR", "internal"


class PredictionFailed(InternalError):
    code = "PREDICTION_FAILED"


class ServiceNotReady(ApiError):
    """The model/explainer or database is not loaded. Startup normally prevents this."""

    status_code, code, category = 503, "SERVICE_NOT_READY", "internal"
