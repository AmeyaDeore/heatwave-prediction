"""Application entry point. Run with: uv run uvicorn heatwave_api.main:app --reload

Startup loads the model, its explainer, the reference data and the database once
(Part 07 §5). Any failure there stops the process with the reason and the command
that fixes it, instead of starting a service that fails on its first prediction.
"""

import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from heatwave_api import __version__
from heatwave_api.api import router
from heatwave_api.config import Settings, get_settings
from heatwave_api.observability import configure_logging, request_id_from, request_id_var
from heatwave_api.responses import error_response, install_error_handlers
from heatwave_api.services import Services, build_services

log = logging.getLogger("heatwave_api")


def create_app(
    settings: Settings | None = None,
    services_factory: Callable[[Settings], Services] = build_services,
    *,
    configure_logs: bool = True,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if configure_logs:
            configure_logging(settings.log_level)
        started = time.perf_counter()
        try:
            app.state.services = services_factory(settings)
        except Exception:
            log.critical("startup failed; the service will not start", exc_info=True)
            raise
        services = app.state.services
        log.info(
            "service ready",
            extra={
                "startup_ms": round((time.perf_counter() - started) * 1000),
                "model_version": services.model.model_version,
                "explainer_id": services.model.explainer_id,
                "database": str(services.db.path),
                "environment": settings.app_env,
            },
        )
        yield

    app = FastAPI(
        title="Heatwave Early Warning API",
        version=__version__,
        description=(
            "Short-term (1-3 day) heatwave risk predictions with SHAP explanations, "
            "alerts and analytics for local authorities. Every response uses one "
            "envelope: {status, data, error, meta}. Contract: docs/api/README.md."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        # Bearer tokens in a header, not cookies: no credentialed CORS needed.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After", "Location"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next) -> Response:
        request_id = request_id_from(request.headers.get("X-Request-ID"))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Anything no handler claimed: a bug. Log it with the stack; the client
            # gets the request id to quote, never the stack trace.
            log.exception("unhandled error", extra={"path": request.url.path})
            response = error_response(
                500,
                "INTERNAL_ERROR",
                "internal",
                "Something went wrong on our side. Quote the request id if you report it.",
            )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": latency_ms,
                "client": request.client.host if request.client else None,
                **getattr(request.state, "log_fields", {}),
            },
        )
        request_id_var.reset(token)
        return response

    install_error_handlers(app)
    app.include_router(router)

    @app.get("/health", tags=["service"])
    def liveness() -> dict[str, str]:
        """Liveness for process supervisors: the process is up and serving requests.
        Readiness, with the model version, is /api/v1/health."""
        return {"status": "ok", "env": settings.app_env}

    return app


app = create_app()
