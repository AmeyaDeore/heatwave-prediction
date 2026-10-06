"""Request and response bodies: the API contract (docs/api/README.md), as Pydantic models.

Every response is an ``Envelope`` (success) or an ``ErrorEnvelope`` (failure), so the
frontend handles both uniformly. The OpenAPI schema at /docs is generated from these
models and exported to docs/api/openapi.json.

The prediction models mirror the Part 06 explanation contract field for field
(docs/ml/explainability.md §3), so a drift in the ML output fails validation here
instead of reaching the dashboard.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION = "v1"

RiskClass = Literal["NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"]
AlertStatus = Literal["DRAFT", "READY", "ISSUED"]
Channel = Literal[
    "PUBLIC_MOBILE_ALERT",
    "GOVERNMENT_PORTAL",
    "PUBLIC_DISPLAY_BOARDS",
    "EMERGENCY_SERVICES",
    "HOSPITALS_HEALTH_CENTRES",
]
DeliveryStatus = Literal["READY", "PENDING", "NOTIFIED", "FAILED"]
SnapshotKind = Literal["ACTUAL", "FORECAST"]
WeatherSource = Literal["open_meteo_forecast", "client"]
PeriodName = Literal["week", "month", "season"]

REGION_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class Strict(BaseModel):
    """Request bodies: unknown fields are an error, never silently ignored."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# -- the envelope -----------------------------------------------------------------------


class Meta(BaseModel):
    request_id: str
    api_version: str = API_VERSION
    # Non-fatal problems the caller should see, e.g. a channel that failed to deliver.
    warnings: list[str] = Field(default_factory=list)
    # POST /alerts only: true when this response replays an earlier identical request.
    idempotent_replay: bool | None = None


class ErrorBody(BaseModel):
    code: str = Field(examples=["UNKNOWN_REGION"])
    category: Literal["client", "auth", "upstream", "internal"]
    message: str
    details: Any = None


class Envelope[T](BaseModel):
    status: Literal["success"] = "success"
    data: T
    error: None = None
    meta: Meta


class ErrorEnvelope(BaseModel):
    status: Literal["error"] = "error"
    data: None = None
    error: ErrorBody
    meta: Meta


# -- shared pieces ----------------------------------------------------------------------


class RegionRef(BaseModel):
    id: str
    name: str
    district: str
    state: str
    zone: str
    lat: float
    lon: float


class Probabilities(BaseModel):
    NORMAL: float
    HEATWAVE: float
    SEVERE_HEATWAVE: float


class UserRef(BaseModel):
    username: str
    display_name: str


# -- predictions ------------------------------------------------------------------------


class Conditions(Strict):
    """One day of raw weather for a caller-supplied ("what-if") prediction.

    Canonical units (docs/data/raw-landing-zone.md). Only ``tmax_c`` is required. A
    missing optional value is imputed by the model's fitted imputer, and the response
    flags it (``imputed: true``) wherever it appears.
    """

    date: date
    tmax_c: float = Field(ge=-20, le=60, description="Daily maximum temperature, °C")
    rh_pct: float | None = Field(None, ge=0, le=100, description="Mean relative humidity, %")
    wind_ms: float | None = Field(None, ge=0, le=75, description="Mean wind speed, m/s")
    wind_height_m: float | None = Field(
        None, gt=0, le=100, description="Height wind_ms was measured at, m (required with it)"
    )
    solar_mj_m2: float | None = Field(None, ge=0, le=45, description="Shortwave, MJ/m²/day")
    precip_mm: float | None = Field(None, ge=0, le=1000, description="Precipitation, mm/day")

    @model_validator(mode="after")
    def _wind_needs_its_height(self):
        # 10 m and 2 m wind differ by ~25 %; guessing the height would silently skew it.
        if self.wind_ms is not None and self.wind_height_m is None:
            raise ValueError("wind_height_m is required when wind_ms is given (10 or 2, usually)")
        return self


class PredictRequest(Strict):
    region_id: str = Field(pattern=REGION_ID_PATTERN, examples=["mumbai"])
    forecast_days: int | None = Field(
        None,
        ge=1,
        le=3,
        description="Predict the next N days of the live forecast (default 3). "
        "Not allowed together with conditions.",
    )
    conditions: list[Conditions] | None = Field(
        None,
        min_length=1,
        max_length=3,
        description="Supply the weather yourself instead of fetching the forecast.",
    )

    @model_validator(mode="after")
    def _one_source(self):
        if self.conditions is not None:
            if self.forecast_days is not None:
                raise ValueError("give either forecast_days or conditions, not both")
            dates = [c.date for c in self.conditions]
            if len(set(dates)) != len(dates):
                raise ValueError("conditions must have one entry per date")
        return self


class Factor(BaseModel):
    rank: int
    feature: str
    label: str
    unit: str
    value: float
    display_value: str
    imputed: bool
    contribution: float
    share_pct: float
    direction: Literal["increases_risk", "decreases_risk", "neutral"]


class Explanation(BaseModel):
    target_class: RiskClass
    reference_class: Literal["NORMAL"]
    quantity: Literal["log_odds", "probability"]
    explained: str
    baseline: float
    output: float
    factors: list[Factor]
    summary: str
    model_version: str
    explainer_id: str


class InputValue(BaseModel):
    """A feature value the model used: the dashboard's metric cards read these."""

    label: str
    unit: str
    value: float
    display_value: str
    imputed: bool


class DailyPrediction(BaseModel):
    date: date
    lead_days: int
    risk_class: RiskClass
    risk_label: str
    confidence: float
    probabilities: Probabilities
    inputs: dict[str, InputValue]
    explanation: Explanation


class RecommendedAction(BaseModel):
    rank: int
    code: str
    text: str
    reason: str


class ForecastWindow(BaseModel):
    start: date
    end: date
    days: int
    label: str = Field(examples=["Next 3 days"])


class SourceInfo(BaseModel):
    weather: WeatherSource
    issued_at: datetime | None
    fetched_at: datetime | None


class ModelInfo(BaseModel):
    model_version: str
    explainer_id: str


class Prediction(BaseModel):
    """One prediction run: every day of the window, with the riskiest day on top.

    The top-level risk/inputs/explanation fields are those of ``peak_date`` (the day
    with the highest risk class; ties go to the higher 1 - P(NORMAL), then the earlier
    date). ``daily`` has every day, each with its own explanation.
    """

    prediction_id: str
    region: RegionRef
    created_at: datetime
    forecast_window: ForecastWindow
    peak_date: date
    risk_class: RiskClass
    risk_label: str
    confidence: float
    probabilities: Probabilities
    inputs: dict[str, InputValue]
    explanation: Explanation
    recommended_actions: list[RecommendedAction]
    actions_version: str
    daily: list[DailyPrediction]
    source: SourceInfo
    model: ModelInfo


class PredictionSummary(BaseModel):
    prediction_id: str
    created_at: datetime
    forecast_window: ForecastWindow
    peak_date: date
    risk_class: RiskClass
    risk_label: str
    confidence: float


class LatestPredictions(BaseModel):
    items: list[Prediction]
    missing_regions: list[str] = Field(
        description="Monitored regions with no stored prediction yet."
    )


# -- weather ----------------------------------------------------------------------------


class CurrentConditions(BaseModel):
    date: date
    kind: SnapshotKind
    source: str
    issued_at: datetime | None
    fetched_at: datetime
    tmax_c: float | None
    normal_tmax_c: float | None
    temp_deviation_c: float | None
    rh_pct: float | None
    wind_ms: float | None = Field(description="m/s at 2 m (converted from the source height)")
    solar_mj_m2: float | None
    precip_mm: float | None
    display: dict[str, str] = Field(description="Formatted values, e.g. '+3.0 °C'")


class RegionWeather(BaseModel):
    region: RegionRef
    current: CurrentConditions | None
    latest_prediction: PredictionSummary | None
    error: ErrorBody | None = Field(
        None, description="Set when this region's weather could not be fetched."
    )


class WeatherList(BaseModel):
    items: list[RegionWeather]


# -- alerts -----------------------------------------------------------------------------


class AlertCreate(Strict):
    client_request_id: UUID = Field(
        description="Generated by the client once per form submission. A retry with the "
        "same id and body returns the original alert instead of creating a second one."
    )
    region_id: str = Field(pattern=REGION_ID_PATTERN)
    severity: RiskClass
    message: str = Field(min_length=1, max_length=1000)
    channels: list[Channel] = Field(min_length=1, max_length=5)
    status: AlertStatus = "DRAFT"
    prediction_id: str | None = Field(None, max_length=64)

    @field_validator("channels")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("each channel may be listed once")
        return value


class AlertUpdate(Strict):
    region_id: str | None = Field(None, pattern=REGION_ID_PATTERN)
    severity: RiskClass | None = None
    message: str | None = Field(None, min_length=1, max_length=1000)
    channels: list[Channel] | None = Field(None, min_length=1, max_length=5)
    status: AlertStatus | None = None
    prediction_id: str | None = Field(None, max_length=64)

    @field_validator("channels")
    @classmethod
    def _unique(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("each channel may be listed once")
        return value

    @model_validator(mode="after")
    def _not_empty(self):
        if not self.model_fields_set:
            raise ValueError("give at least one field to change")
        return self


class ChannelDelivery(BaseModel):
    channel: Channel
    label: str
    status: DeliveryStatus
    attempts: int
    last_error: str | None
    updated_at: datetime


class Alert(BaseModel):
    alert_id: str = Field(examples=["HW-2026-0007"])
    status: AlertStatus
    severity: RiskClass
    severity_label: str
    region: RegionRef
    message: str
    channels: list[ChannelDelivery]
    delivery_summary: dict[str, int]
    prediction_id: str | None
    created_at: datetime
    created_by: UserRef
    updated_at: datetime
    issued_at: datetime | None
    issued_by: UserRef | None


class AlertPage(BaseModel):
    items: list[Alert]
    total: int
    limit: int
    offset: int


# -- analytics --------------------------------------------------------------------------


class Period(BaseModel):
    name: PeriodName
    start: date
    end: date
    days: int


class TrendPoint(BaseModel):
    date: date
    kind: SnapshotKind
    tmax_c: float | None
    normal_tmax_c: float | None
    temp_deviation_c: float | None
    heatwave_threshold_c: float | None = Field(
        description="Tmax at or above which the IMD rule calls this day a heatwave "
        "(region only; null for an all-region average)."
    )
    severe_threshold_c: float | None
    above_heatwave_threshold: bool | None


class RiskShare(BaseModel):
    risk_class: RiskClass
    label: str
    region_days: int
    pct: float


class RiskDistribution(BaseModel):
    total_region_days: int
    classes: list[RiskShare]


class MonthEvents(BaseModel):
    month: str = Field(examples=["2026-05"])
    heatwave_days: int
    severe_heatwave_days: int
    event_days: int


class ModelPerformance(BaseModel):
    model_version: str
    model_family: str
    explainer_id: str | None
    evaluation_id: str
    policy_version: str
    report: str
    test_rows: int
    averaging: Literal["macro"] = "macro"
    precision: float
    recall: float
    f1: float
    accuracy: float
    confidence: float = Field(description="Mean top-class probability on the test split")
    top_label_ece: float
    per_class: dict[str, dict[str, float]]
    deployed_at: datetime


class Analytics(BaseModel):
    region: RegionRef | None
    period: Period
    temperature_trend: list[TrendPoint]
    risk_distribution: RiskDistribution
    heatwave_events: list[MonthEvents]
    event_rule: str
    model_performance: ModelPerformance | None


# -- auth -------------------------------------------------------------------------------


class LoginRequest(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class User(BaseModel):
    id: int
    username: str
    display_name: str
    role: str


class Session(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: User


# -- reference and health ---------------------------------------------------------------


class CodeLabel(BaseModel):
    code: str
    label: str


class Reference(BaseModel):
    regions: list[RegionRef]
    risk_classes: list[CodeLabel]
    alert_statuses: list[str]
    alert_channels: list[CodeLabel]
    delivery_statuses: list[str]
    features: dict[str, dict[str, Any]]
    max_forecast_days: int


class Health(BaseModel):
    status: Literal["ready"]
    environment: str
    model_version: str
    model_family: str
    explainer_id: str
    database: Literal["ok"]
    notifications_mode: str
    started_at: datetime
