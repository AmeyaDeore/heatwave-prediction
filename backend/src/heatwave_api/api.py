"""The versioned API: /api/v1/... (contract: docs/api/README.md).

Handlers stay thin: validate (Pydantic), delegate, wrap the result in the envelope.
They are plain ``def`` functions, so FastAPI runs them in its thread pool and the
blocking SQLite and model calls never stall the event loop.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from heatwave_api import alerts as alert_service
from heatwave_api import analytics as analytics_service
from heatwave_api import predictions as prediction_service
from heatwave_api.db.repository import Repository
from heatwave_api.deps import current_user, get_repo, get_services, rate_limit, reader
from heatwave_api.errors import NotFound, ServiceNotReady, Unauthenticated
from heatwave_api.responses import COMMON_ERRORS, ok
from heatwave_api.schemas import (
    REGION_ID_PATTERN,
    Alert,
    AlertCreate,
    AlertPage,
    AlertStatus,
    AlertUpdate,
    Analytics,
    Envelope,
    ErrorEnvelope,
    Health,
    LatestPredictions,
    LoginRequest,
    ModelPerformance,
    Prediction,
    PredictRequest,
    Reference,
    Session,
    User,
    WeatherList,
)
from heatwave_api.security import dummy_hash, verify_password
from heatwave_api.services import Services

PREFIX = "/api/v1"
router = APIRouter(
    prefix=PREFIX,
    responses={code: {"model": ErrorEnvelope, **r} for code, r in COMMON_ERRORS.items()},
)

RegionQuery = Annotated[str | None, Query(pattern=REGION_ID_PATTERN)]
AlertCode = Annotated[str, Path(pattern=r"^HW-\d{4}-\d{4,}$", examples=["HW-2026-0001"])]
AUTH_ERRORS = {401: {"model": ErrorEnvelope, "description": "Not signed in"}}
NOT_FOUND = {404: {"model": ErrorEnvelope, "description": "Unknown id"}}
UPSTREAM = {
    502: {"model": ErrorEnvelope, "description": "Weather source error"},
    503: {"model": ErrorEnvelope, "description": "Weather source unreachable"},
}


def _user(row: dict) -> dict:
    return {k: row[k] for k in ("id", "username", "display_name", "role")}


# -- service ----------------------------------------------------------------------------


@router.get("/health", tags=["service"], response_model=Envelope[Health])
def readiness(services: Services = Depends(get_services)):
    """Readiness: the model and explainer are loaded and the database answers."""
    try:
        services.db.ping()
    except Exception as exc:
        raise ServiceNotReady("The database is not reachable.") from exc
    return ok(
        {
            "status": "ready",
            "environment": services.settings.app_env,
            "model_version": services.model.model_version,
            "model_family": services.model.model_family,
            "explainer_id": services.model.explainer_id,
            "database": "ok",
            "notifications_mode": services.notifier.mode,
            "started_at": services.started_at,
        }
    )


@router.get("/reference", tags=["service"], response_model=Envelope[Reference])
def reference(services: Services = Depends(get_services), _: dict | None = Depends(reader)):
    """Regions, vocabularies and display labels the frontend renders with."""
    return ok(services.reference.as_payload())


@router.get(
    "/model",
    tags=["service"],
    response_model=Envelope[ModelPerformance],
    responses=NOT_FOUND,
)
def model(repo: Repository = Depends(get_repo), _: dict | None = Depends(reader)):
    """The deployed model and its Part 05 test metrics (static per model version)."""
    performance = analytics_service.model_performance(repo)
    if performance is None:
        raise NotFound("No model is recorded as deployed.", code="MODEL_NOT_RECORDED")
    return ok(performance)


# -- predictions ------------------------------------------------------------------------


@router.post(
    "/predict",
    tags=["predictions"],
    status_code=201,
    response_model=Envelope[Prediction],
    responses=NOT_FOUND | UPSTREAM,
    dependencies=[Depends(rate_limit("predict"))],
)
def predict(
    body: PredictRequest,
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    _: dict | None = Depends(reader),
):
    """Predict heatwave risk for the next 1-3 days of a region, with every day's SHAP
    explanation and the recommended authority actions. The run is stored."""
    result = prediction_service.run_prediction(services, repo, body)
    request.state.log_fields = {
        "region_id": body.region_id,
        "risk_class": result["risk_class"],
        "prediction_id": result["prediction_id"],
        "model_version": result["model"]["model_version"],
        "weather_source": result["source"]["weather"],
    }
    response.headers["Location"] = f"{PREFIX}/predictions/{result['prediction_id']}"
    return ok(result)


@router.get(
    "/predictions/latest",
    tags=["predictions"],
    response_model=Envelope[LatestPredictions],
    responses=NOT_FOUND,
)
def latest_predictions(
    region_id: RegionQuery = None,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    _: dict | None = Depends(reader),
):
    """The most recent stored prediction of each region (or of one region)."""
    return ok(prediction_service.latest_predictions(services, repo, region_id))


@router.get(
    "/predictions/{prediction_id}",
    tags=["predictions"],
    response_model=Envelope[Prediction],
    responses=NOT_FOUND,
)
def get_prediction(
    prediction_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    _: dict | None = Depends(reader),
):
    """A stored prediction, exactly as POST /predict returned it."""
    return ok(prediction_service.stored_prediction(services, repo, prediction_id))


# -- weather ----------------------------------------------------------------------------


@router.get(
    "/weather",
    tags=["weather"],
    response_model=Envelope[WeatherList],
    responses=NOT_FOUND | UPSTREAM,
)
def weather(
    region_id: RegionQuery = None,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    _: dict | None = Depends(reader),
):
    """Today's conditions for every monitored region (or one), with each region's
    latest prediction for the dashboard's regional table."""
    data = analytics_service.current_weather(services, repo, region_id)
    warnings = [
        f"{i['region']['name']}: {i['error']['message']}" for i in data["items"] if i["error"]
    ]
    return ok(data, warnings=warnings)


# -- alerts -----------------------------------------------------------------------------


@router.get("/alerts", tags=["alerts"], response_model=Envelope[AlertPage])
def list_alerts(
    status: Annotated[AlertStatus | None, Query()] = None,
    region_id: RegionQuery = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    _: dict | None = Depends(reader),
):
    """Alerts, newest first, with each channel's delivery status."""
    rows, total = repo.list_alerts(status=status, region_id=region_id, limit=limit, offset=offset)
    items = [alert_service.alert_payload(services, r) for r in rows]
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get(
    "/alerts/{alert_id}", tags=["alerts"], response_model=Envelope[Alert], responses=NOT_FOUND
)
def get_alert(
    alert_id: AlertCode,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    _: dict | None = Depends(reader),
):
    alert = repo.alert(code=alert_id)
    if alert is None:
        raise NotFound(f"No alert '{alert_id}'.", code="ALERT_NOT_FOUND")
    return ok(alert_service.alert_payload(services, alert))


@router.post(
    "/alerts",
    tags=["alerts"],
    status_code=201,
    response_model=Envelope[Alert],
    responses=AUTH_ERRORS
    | NOT_FOUND
    | {
        200: {"model": Envelope[Alert], "description": "Replay of an earlier identical request"},
        409: {
            "model": ErrorEnvelope,
            "description": "client_request_id reused (IDEMPOTENCY_CONFLICT)",
        },
    },
    dependencies=[Depends(rate_limit("alert_writes"))],
)
def create_alert(
    body: AlertCreate,
    response: Response,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    user: dict = Depends(current_user),
):
    """Create an alert as DRAFT, READY or ISSUED. ISSUED dispatches it at once.
    Requires a signed-in user."""
    alert, created, warnings = alert_service.create_alert(services, repo, user, body)
    if not created:
        response.status_code = 200
    response.headers["Location"] = f"{PREFIX}/alerts/{alert['alert_id']}"
    return ok(alert, warnings=warnings, replay=not created)


@router.patch(
    "/alerts/{alert_id}",
    tags=["alerts"],
    response_model=Envelope[Alert],
    responses=AUTH_ERRORS
    | NOT_FOUND
    | {409: {"model": ErrorEnvelope, "description": "Already issued (ALERT_ALREADY_ISSUED)"}},
    dependencies=[Depends(rate_limit("alert_writes"))],
)
def update_alert(
    alert_id: AlertCode,
    body: AlertUpdate,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    user: dict = Depends(current_user),
):
    """Edit a DRAFT/READY alert, or move its status. status=ISSUED issues it:
    the alert is locked and dispatched to its channels. Requires a signed-in user."""
    alert, warnings = alert_service.update_alert(services, repo, user, alert_id, body)
    return ok(alert, warnings=warnings)


# -- analytics --------------------------------------------------------------------------


@router.get(
    "/analytics", tags=["analytics"], response_model=Envelope[Analytics], responses=NOT_FOUND
)
def analytics(
    region_id: RegionQuery = None,
    period: Annotated[Literal["week", "month", "season"], Query()] = "week",
    end_date: Annotated[date | None, Query(description="Default: today (IST)")] = None,
    months: Annotated[int, Query(ge=1, le=24)] = 6,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
    _: dict | None = Depends(reader),
):
    """Temperature trend, risk distribution and monthly heatwave events for a period,
    plus the deployed model's performance."""
    return ok(
        analytics_service.analytics(
            services, repo, region_id=region_id, period=period, end=end_date, months=months
        )
    )


# -- auth -------------------------------------------------------------------------------


@router.post(
    "/auth/login",
    tags=["auth"],
    response_model=Envelope[Session],
    responses=AUTH_ERRORS,
    dependencies=[Depends(rate_limit("login"))],
)
def login(
    body: LoginRequest,
    request: Request,
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
):
    """Exchange a username and password for a bearer token."""
    user = repo.user_by_username(body.username)
    valid = verify_password(body.password, user["password_hash"] if user else dummy_hash())
    if not (user and valid and user["active"]):
        # One message for every cause, so the response does not reveal which usernames exist.
        raise Unauthenticated("Invalid username or password.", code="INVALID_CREDENTIALS")
    token, expires_at, _ = services.tokens.issue(user)
    request.state.log_fields = {"user": user["username"]}
    return ok({"access_token": token, "expires_at": expires_at, "user": _user(user)})


@router.post(
    "/auth/logout",
    tags=["auth"],
    response_model=Envelope[dict[str, bool]],
    responses=AUTH_ERRORS,
)
def logout(repo: Repository = Depends(get_repo), user: dict = Depends(current_user)):
    """Revoke the token this request was made with."""
    claims = user["_claims"]
    repo.revoke_token(claims["jti"], datetime.fromtimestamp(claims["exp"], UTC).isoformat())
    return ok({"signed_out": True})


@router.get("/auth/me", tags=["auth"], response_model=Envelope[User], responses=AUTH_ERRORS)
def me(user: dict = Depends(current_user)):
    return ok(_user(user))
