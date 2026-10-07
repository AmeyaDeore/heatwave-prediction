"""Application factory: wiring, startup checks, middleware and error handlers.

`create_app()` builds the real service. Tests pass fakes for the pieces they replace
(`predictor`, `weather`, `repo`, `notifier`), so each endpoint is testable with no model
or weather file; the database is SQLite (Part 08), in memory for tests.
"""

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import get_args

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from heatwave_api.alerts import AlertService
from heatwave_api.auth import TokenService, User, UserStore, hash_password
from heatwave_api.catalog import Catalog
from heatwave_api.config import Settings, get_settings
from heatwave_api.db.connection import MEMORY, resolve_sqlite_path
from heatwave_api.db.repository import Database, SqliteRepository, SqliteUserStore
from heatwave_api.envelope import ErrorBody, ErrorEnvelope, Meta
from heatwave_api.errors import ApiError, HttpFailure, ModelUnavailable
from heatwave_api.notifier import MockNotifier, Notifier
from heatwave_api.predictor import Predictor, ProductionPredictor
from heatwave_api.ratelimit import RateLimiter
from heatwave_api.repositories import Repository
from heatwave_api.routes import router
from heatwave_api.schemas import RegionOut, RiskClass
from heatwave_api.services import PredictionService, model_performance
from heatwave_api.weather import PipelineWeatherSource, WeatherSource

log = logging.getLogger("heatwave_api")
access_log = logging.getLogger("heatwave_api.access")

DEFAULT_SECRET = "change-me-local-only"  # pragma: allowlist secret
DEMO_USER_ID = "user_demo"
_STANDARD_LOG_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line: endpoint, status, latency and prediction fields are keys."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        entry.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD_LOG_ATTRS})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    logger = logging.getLogger("heatwave_api")
    logger.setLevel(level)
    if not any(getattr(h, "_heatwave", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._heatwave = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.propagate = False


@dataclass
class AppContext:
    settings: Settings
    catalog: Catalog
    predictor: Predictor
    weather: WeatherSource
    repo: Repository
    notifier: Notifier
    users: UserStore
    tokens: TokenService
    limiter: RateLimiter
    predictions: PredictionService
    alerts: AlertService


def _demo_users(settings: Settings) -> list[User]:
    if settings.app_env not in ("local", "test"):
        return []  # real users arrive with Part 15; a deployed service has none until then
    return [
        User(
            id=DEMO_USER_ID,
            username=settings.demo_user_username,
            display_name="Demo Official",
            role="official",
            password_hash=hash_password(settings.demo_user_password.get_secret_value()),
        )
    ]


def open_database(settings: Settings, catalog: Catalog) -> Database:
    """Open the database and bring it to the code's schema version.

    local/test apply pending migrations automatically. staging/production refuse to
    start instead: there, migrating is an explicit, backed-up deploy step
    (`heatwave-db backup && heatwave-db migrate`, docs/database/README.md §6).
    An in-memory database is always new, so it is always migrated.
    """
    db = Database.open(settings.database_url)
    if (
        settings.app_env in ("local", "test")
        or resolve_sqlite_path(settings.database_url) == MEMORY
    ):
        applied = db.migrate()
        if applied:
            log.info("database migrated", extra={"applied": applied})
    elif pending := db.pending_migrations():
        db.close()
        raise RuntimeError(
            f"Database has pending migrations {pending}. Run `heatwave-db migrate` first."
        )
    # config/regions.yaml stays the source of truth; the table mirrors it for FKs.
    SqliteRepository(db).upsert_regions(RegionOut(**r.__dict__) for r in catalog.regions.values())
    return db


def check_startup(settings: Settings, catalog: Catalog) -> None:
    """Fail fast on configuration that would only hurt later."""
    if tuple(get_args(RiskClass)) != catalog.risk_classes:
        raise ModelUnavailable(
            f"Risk classes in the API {get_args(RiskClass)} differ from "
            f"config/risk_classes.yaml {catalog.risk_classes}."
        )
    if settings.app_env in ("staging", "production"):
        if settings.auth_secret_key.get_secret_value() == DEFAULT_SECRET:
            raise RuntimeError("AUTH_SECRET_KEY is the local default; set a real secret.")
        if settings.notifications_mode == "mock":
            log.warning(
                "NOTIFICATIONS_MODE=mock in %s: no alert will really be sent", settings.app_env
            )


def build_context(
    settings: Settings,
    *,
    predictor: Predictor | None = None,
    weather: WeatherSource | None = None,
    repo: Repository | None = None,
    notifier: Notifier | None = None,
    users: UserStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> AppContext:
    catalog = Catalog.load(settings)
    check_startup(settings, catalog)
    predictor = predictor or ProductionPredictor.load(settings)
    weather = weather or PipelineWeatherSource(settings.weather_features_file)
    if repo is None or users is None:
        db = open_database(settings, catalog)
        repo = repo or SqliteRepository(db)
        if users is None:
            store = SqliteUserStore(db)
            demo = _demo_users(settings)
            for user in demo:
                store.upsert(user)
            if not demo:  # e.g. a database copied from local: a known password must not work
                store.deactivate(DEMO_USER_ID)
            users = store
    repo.record_active_model(model_performance(predictor))
    notifier = notifier or MockNotifier()
    return AppContext(
        settings=settings,
        catalog=catalog,
        predictor=predictor,
        weather=weather,
        repo=repo,
        notifier=notifier,
        users=users,
        tokens=TokenService(
            settings.auth_secret_key.get_secret_value(), settings.auth_token_ttl_minutes
        ),
        limiter=RateLimiter(
            {
                "predict": settings.rate_limit_predict_per_minute,
                "alerts": settings.rate_limit_alerts_per_minute,
                "login": settings.rate_limit_login_per_minute,
            }
        ),
        predictions=PredictionService(
            predictor, weather, repo, catalog, settings.weather_stale_after_hours
        ),
        alerts=AlertService(repo, catalog, notifier, *([clock] if clock else [])),
    )


def _error_response(request: Request, exc: ApiError) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorBody(kind=exc.kind, code=exc.code, message=exc.message, details=exc.details),
        meta=Meta(request_id=getattr(request.state, "request_id", "unknown")),
    )
    return JSONResponse(
        body.model_dump(mode="json"), status_code=exc.status_code, headers=exc.headers
    )


def create_app(settings: Settings | None = None, **overrides) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Any failure here stops the process: a broken service must not look healthy.
        app.state.ctx = build_context(settings, **overrides)
        info = app.state.ctx.predictor.info
        log.info(
            "startup complete",
            extra={"model_version": info.model_version, "explainer_id": info.explainer_id},
        )
        yield
        if isinstance(db := getattr(app.state.ctx.repo, "db", None), Database):
            db.close()

    app = FastAPI(
        title="Heatwave Early Warning API",
        version="1.0.0",
        description="Predictions with SHAP explanations, weather, alerts and analytics.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.log_fields = {}
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            access_log.info(
                "request",
                extra={
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "user_id": getattr(request.state, "user_id", None),
                    **request.state.log_fields,
                },
            )

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        level = logging.ERROR if exc.kind == "internal" else logging.WARNING
        cause = exc.__cause__
        log.log(
            level,
            exc.message,
            extra={"request_id": request.state.request_id, "code": exc.code, "kind": exc.kind},
            exc_info=(type(cause), cause, cause.__traceback__) if cause else None,
        )
        return _error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Only where and why: never echo the submitted value back.
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return _error_response(
            request,
            HttpFailure(422, "VALIDATION_ERROR", "The request is not valid.", details=details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return _error_response(
            request,
            HttpFailure(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.error(
            "unhandled error",
            extra={"request_id": request.state.request_id},
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _error_response(
            request,
            HttpFailure(
                500,
                "INTERNAL_ERROR",
                f"Something went wrong on our side. Quote request id {request.state.request_id}.",
                kind="internal",
            ),
        )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness only: the process is up. Readiness (model, data) is /api/v1/health/ready."""
        return {"status": "ok", "env": settings.app_env}

    app.include_router(router)
    return app
