"""Building the envelope, and turning every kind of failure into one."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from heatwave_api.errors import ApiError
from heatwave_api.observability import request_id_var
from heatwave_api.schemas import API_VERSION

log = logging.getLogger(__name__)

# Shown in OpenAPI on every versioned route.
COMMON_ERRORS = {
    422: {"description": "Invalid input (VALIDATION_ERROR)"},
    429: {"description": "Rate limited (RATE_LIMITED)"},
    500: {"description": "Internal failure"},
}


def meta(warnings: list[str] | None = None, replay: bool | None = None) -> dict:
    return {
        "request_id": request_id_var.get(),
        "api_version": API_VERSION,
        "warnings": warnings or [],
        "idempotent_replay": replay,
    }


def ok(data, *, warnings: list[str] | None = None, replay: bool | None = None) -> dict:
    return {"status": "success", "data": data, "error": None, "meta": meta(warnings, replay)}


def error_response(
    status_code: int,
    code: str,
    category: str,
    message: str,
    details=None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "status": "error",
        "data": None,
        "error": {"code": code, "category": category, "message": message, "details": details},
        "meta": meta(),
    }
    return JSONResponse(body, status_code=status_code, headers=headers)


def _log_error(request: Request, exc: ApiError) -> None:
    level = {"internal": logging.ERROR, "upstream": logging.WARNING}.get(exc.category, logging.INFO)
    log.log(
        level,
        "request failed",
        extra={
            "error_code": exc.code,
            "error_category": exc.category,
            "path": request.url.path,
            "cause": repr(exc.__cause__) if exc.__cause__ else None,
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        _log_error(request, exc)
        return error_response(
            exc.status_code, exc.code, exc.category, exc.message, exc.details, exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo the submitted values back: they can include a password.
        details = [
            {
                "loc": [p for p in e.get("loc", ()) if p != "body"],
                "msg": e.get("msg"),
                "type": e.get("type"),
            }
            for e in exc.errors()
        ]
        return error_response(
            422, "VALIDATION_ERROR", "client", "The request is not valid.", details
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        message = {404: "No such endpoint.", 405: "Method not allowed."}.get(
            exc.status_code, str(exc.detail)
        )
        return error_response(
            exc.status_code,
            codes.get(exc.status_code, "HTTP_ERROR"),
            "client",
            message,
            headers=getattr(exc, "headers", None),
        )
