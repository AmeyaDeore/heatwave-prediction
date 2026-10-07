"""All /api/v1 endpoints. Contracts are in docs/api/README.md.

Protected (bearer token): POST/PATCH alerts. Everything else is read-only.
Rate limited: predict, alert writes and login.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from heatwave_api import services
from heatwave_api.auth import User, authenticate, current_user
from heatwave_api.envelope import Envelope, Meta
from heatwave_api.errors import ApiError, NotFound, UpstreamUnavailable
from heatwave_api.ratelimit import limit
from heatwave_api.schemas import (
    AlertCreate,
    AlertList,
    AlertOut,
    AlertStatus,
    AlertUpdate,
    AnalyticsOut,
    ChannelOut,
    LoginRequest,
    PredictionOut,
    PredictRequest,
    ReadinessOut,
    RegionId,
    RegionOut,
    TokenOut,
    UserOut,
    WeatherOut,
)

router = APIRouter(prefix="/api/v1")

RegionQuery = Annotated[RegionId | None, Query(description="A region id from config/regions.yaml")]


def ctx(request: Request):
    return request.app.state.ctx


def ok(request: Request, data):
    return {"status": "ok", "data": data, "meta": Meta(request_id=request.state.request_id)}


# -- reference data -------------------------------------------------------------------


@router.get("/regions", response_model=Envelope[list[RegionOut]], tags=["reference"])
def list_regions(request: Request):
    return ok(request, [RegionOut(**r.__dict__) for r in ctx(request).catalog.regions.values()])


@router.get("/alert-channels", response_model=Envelope[list[ChannelOut]], tags=["reference"])
def list_channels(request: Request):
    return ok(request, [ChannelOut(**c.__dict__) for c in ctx(request).catalog.channels.values()])


# -- prediction -----------------------------------------------------------------------


@router.post(
    "/predict",
    response_model=Envelope[PredictionOut],
    tags=["prediction"],
    dependencies=[Depends(limit("predict"))],
)
def predict(body: PredictRequest, request: Request):
    """Score a region's conditions for today or the next 1-3 days, with SHAP factors."""
    prediction = ctx(request).predictions.predict(body.region_id, body.lead_days)
    request.state.log_fields = {
        "risk_class": prediction.risk_class,
        "region_id": body.region_id,
        "lead_days": body.lead_days,
    }
    return ok(request, prediction)


@router.get(
    "/predictions/latest",
    response_model=Envelope[PredictionOut],
    tags=["prediction"],
)
def latest_prediction(
    request: Request,
    region_id: RegionId,
    lead_days: Annotated[int, Query(ge=0, le=3)] = 0,
):
    """The most recent stored prediction, without recomputing (what the dashboard reads)."""
    services.region_out(ctx(request).catalog, region_id)
    found = ctx(request).repo.latest_prediction(region_id, lead_days)
    if found is None:
        raise NotFound(f"No prediction has been made for '{region_id}' at lead {lead_days}.")
    return ok(request, found)


@router.get(
    "/predictions/{prediction_id}", response_model=Envelope[PredictionOut], tags=["prediction"]
)
def get_prediction(request: Request, prediction_id: str):
    found = ctx(request).repo.get_prediction(prediction_id)
    if found is None:
        raise NotFound(f"Prediction '{prediction_id}' does not exist.")
    return ok(request, found)


# -- weather --------------------------------------------------------------------------


@router.get("/weather", response_model=Envelope[list[WeatherOut]], tags=["weather"])
def weather(
    request: Request,
    region_id: RegionQuery = None,
    lead_days: Annotated[int, Query(ge=0, le=3)] = 0,
):
    """Conditions for one region, or for every monitored region when `region_id` is omitted."""
    c = ctx(request)
    if region_id is not None:
        services.region_out(c.catalog, region_id)
        readings = [c.weather.reading(region_id, lead_days)]
    else:
        readings = [r for r in c.weather.current() if r.region_id in c.catalog.regions]
        if not readings:
            raise UpstreamUnavailable("No current weather data is available for any region.")
    return ok(
        request,
        [
            services.weather_out(r, c.catalog, c.predictor, c.settings.weather_stale_after_hours)
            for r in readings
        ],
    )


# -- alerts ---------------------------------------------------------------------------


@router.get("/alerts", response_model=Envelope[AlertList], tags=["alerts"])
def list_alerts(
    request: Request,
    status: AlertStatus | None = None,
    region_id: RegionQuery = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    alerts, total = ctx(request).repo.list_alerts(
        status=status, region_id=region_id, limit=limit, offset=offset
    )
    return ok(request, AlertList(alerts=alerts, total=total, limit=limit, offset=offset))


@router.get("/alerts/{alert_id}", response_model=Envelope[AlertOut], tags=["alerts"])
def get_alert(request: Request, alert_id: str):
    return ok(request, ctx(request).alerts.get(alert_id))


@router.post(
    "/alerts",
    response_model=Envelope[AlertOut],
    status_code=201,
    tags=["alerts"],
    dependencies=[Depends(limit("alerts"))],
)
def create_alert(
    body: AlertCreate,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user)],
):
    """Create a DRAFT, or issue immediately with `status: ISSUED`. Replays are idempotent."""
    alert = ctx(request).alerts.create(body, user.id)
    if alert.idempotent_replay:
        response.status_code = 200
    request.state.log_fields = {"alert_id": alert.alert_id, "alert_status": alert.status}
    return ok(request, alert)


@router.patch(
    "/alerts/{alert_id}",
    response_model=Envelope[AlertOut],
    tags=["alerts"],
    dependencies=[Depends(limit("alerts"))],
)
def update_alert(
    alert_id: str,
    body: AlertUpdate,
    request: Request,
    user: Annotated[User, Depends(current_user)],
):
    """Edit a DRAFT/READY alert, or move it to READY / ISSUED (`status`)."""
    alert = ctx(request).alerts.update(alert_id, body)
    request.state.log_fields = {"alert_id": alert.alert_id, "alert_status": alert.status}
    return ok(request, alert)


# -- analytics ------------------------------------------------------------------------


@router.get("/analytics", response_model=Envelope[AnalyticsOut], tags=["analytics"])
def analytics(
    request: Request,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    region_id: RegionQuery = None,
):
    c = ctx(request)
    return ok(request, services.analytics(c.repo, c.predictor, c.catalog, days, region_id))


# -- auth -----------------------------------------------------------------------------


@router.post(
    "/auth/login",
    response_model=Envelope[TokenOut],
    tags=["auth"],
    dependencies=[Depends(limit("login"))],
)
def login(body: LoginRequest, request: Request):
    c = ctx(request)
    user = authenticate(c.users, body.username, body.password)
    token, expires = c.tokens.issue(user, datetime.now(UTC))
    request.state.user_id = user.id
    return ok(request, TokenOut(access_token=token, expires_at=expires, user=user.public()))


@router.get("/auth/me", response_model=Envelope[UserOut], tags=["auth"])
def me(request: Request, user: Annotated[User, Depends(current_user)]):
    return ok(request, user.public())


# -- health ---------------------------------------------------------------------------


@router.get("/health/ready", response_model=Envelope[ReadinessOut], tags=["health"])
def ready(request: Request, response: Response):
    """Readiness: model loaded (guaranteed by startup) and weather data present and fresh."""
    c = ctx(request)
    issued_at, state = None, "ok"
    try:
        readings = c.weather.current()
        if not readings:
            raise UpstreamUnavailable("empty")
        issued_at = max(r.issued_at for r in readings)
        if min(r.age_hours() for r in readings) > c.settings.weather_stale_after_hours:
            state = "stale"
    except ApiError:
        state = "unavailable"
    data = ReadinessOut(
        ready=state != "unavailable" and c.repo.ping(),
        model_version=c.predictor.info.model_version,
        explainer_id=c.predictor.info.explainer_id,
        weather_data=state,
        weather_issued_at=issued_at,
    )
    if not data.ready:
        response.status_code = 503  # probes act on the status code alone
    return ok(request, data)
