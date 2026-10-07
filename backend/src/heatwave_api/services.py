"""Application services behind the routers: prediction and analytics."""

import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from heatwave_api.catalog import Catalog
from heatwave_api.errors import UnknownRegion
from heatwave_api.predictor import Predictor
from heatwave_api.repositories import Repository
from heatwave_api.schemas import (
    AnalyticsOut,
    ForecastWindow,
    ModelPerformance,
    MonthlyCount,
    PredictionOut,
    RegionOut,
    TrendPoint,
    WeatherOut,
    WeatherProvenance,
)
from heatwave_api.weather import WeatherReading, WeatherSource

log = logging.getLogger("heatwave_api.predict")


def region_out(catalog: Catalog, region_id: str) -> RegionOut:
    region = catalog.regions.get(region_id)
    if region is None:
        raise UnknownRegion(f"Unknown region '{region_id}'.")
    return RegionOut(**region.__dict__)


def provenance(reading: WeatherReading, stale_after_hours: int, now: datetime) -> WeatherProvenance:
    age = reading.age_hours(now)
    return WeatherProvenance(
        source=reading.source,
        issued_at=reading.issued_at,
        age_hours=round(age, 1),
        stale=age > stale_after_hours,
    )


class PredictionService:
    def __init__(
        self,
        predictor: Predictor,
        weather: WeatherSource,
        repo: Repository,
        catalog: Catalog,
        stale_after_hours: int,
    ):
        self.predictor, self.weather, self.repo = predictor, weather, repo
        self.catalog, self.stale_after_hours = catalog, stale_after_hours

    def predict(self, region_id: str, lead_days: int) -> PredictionOut:
        region = region_out(self.catalog, region_id)  # 404 before touching weather or model
        reading = self.weather.reading(region_id, lead_days)
        result = self.predictor.predict(reading)
        body = result.prediction
        now = datetime.now(UTC)
        prediction = PredictionOut(
            prediction_id=f"pred_{uuid4().hex[:16]}",
            created_at=now,
            region=region,
            forecast_window=ForecastWindow(
                valid_date=reading.date, lead_days=lead_days, issued_at=reading.issued_at
            ),
            risk_class=body["risk_class"],
            confidence=body["confidence"],
            probabilities=body["probabilities"],
            inputs=result.inputs,
            explanation=body["explanation"],
            recommended_actions=self.catalog.recommended_actions(
                body["risk_class"], body["explanation"]["factors"]
            ),
            actions_version=self.catalog.actions_version,
            weather=provenance(reading, self.stale_after_hours, now),
        )
        self.repo.add_prediction(prediction)
        return prediction


def weather_out(
    reading: WeatherReading, catalog: Catalog, predictor: Predictor, stale_after_hours: int
) -> WeatherOut:
    """Conditions plus the two derived numbers the dashboard shows (normal and deviation),
    computed by the shared feature path, never re-derived here."""
    inputs = predictor.inputs(reading)
    return WeatherOut(
        region=region_out(catalog, reading.region_id),
        date=reading.date,
        lead_days=reading.lead_days,
        tmax_c=reading.tmax_c,
        normal_tmax_c=inputs["normal_tmax_c"],
        temp_deviation_c=inputs["temp_deviation_c"],
        rh_pct=reading.rh_pct,
        wind_ms=reading.wind_ms,
        solar_mj_m2=reading.solar_mj_m2,
        precip_mm=reading.precip_mm,
        provenance=provenance(reading, stale_after_hours, datetime.now(UTC)),
    )


def model_performance(predictor: Predictor) -> ModelPerformance:
    """Static per deployed model version: read from Part 05's promotion pointer, once."""
    info, ev = predictor.info, predictor.info.evaluation
    metrics = ev["test_metrics"]
    return ModelPerformance(
        model_version=info.model_version,
        model_family=info.model_family,
        explainer_id=info.explainer_id,
        labeling_rule_version=info.labeling_rule_version,
        evaluated_on=f"held-out test split ({ev['evaluation_id']}, policy {ev['policy_version']})",
        test_rows=ev["test_rows"],
        accuracy=metrics["accuracy"],
        precision_macro=metrics["precision_macro"],
        recall_macro=metrics["recall_macro"],
        f1_macro=metrics["f1_macro"],
        per_class={
            name: {k: v for k, v in scores.items() if k != "support"}
            for name, scores in metrics["per_class"].items()
        },
        mean_confidence=ev["calibration"]["mean_confidence"],
        calibration_ece=ev["calibration"]["top_label_ece"],
    )


def analytics(
    repo: Repository, predictor: Predictor, catalog: Catalog, days: int, region_id: str | None
) -> AnalyticsOut:
    if region_id is not None:
        region_out(catalog, region_id)
    since = datetime.now(UTC) - timedelta(days=days)
    stored = repo.predictions_since(since, region_id)

    # One point per forecast date: the newest prediction for each region-date.
    latest: dict[tuple[str, str], PredictionOut] = {}
    for p in stored:
        latest[(p.region.id, p.forecast_window.valid_date.isoformat())] = p
    unique = list(latest.values())

    by_day: dict[str, list[float]] = defaultdict(list)
    monthly: dict[str, Counter] = defaultdict(Counter)
    distribution: Counter = Counter({c: 0 for c in catalog.risk_classes})
    for p in unique:
        distribution[p.risk_class] += 1
        month = p.forecast_window.valid_date.strftime("%Y-%m")
        monthly[month][p.risk_class] += 1
        tmax = p.inputs.get("tmax_c")
        if tmax is not None:
            by_day[p.forecast_window.valid_date.isoformat()].append(tmax)

    return AnalyticsOut(
        period_days=days,
        region_id=region_id,
        data_source="stored_predictions",
        temperature_trend=[
            TrendPoint(
                date=day,
                avg_tmax_c=round(sum(v) / len(v), 2),
                max_tmax_c=max(v),
                predictions=len(v),
            )
            for day, v in sorted(by_day.items())
        ],
        events_per_month=[
            MonthlyCount(month=m, heatwave_events=c["HEATWAVE"], severe_events=c["SEVERE_HEATWAVE"])
            for m, c in sorted(monthly.items())
        ],
        risk_distribution=dict(distribution),
        predictions_in_period=len(unique),
        # Read from model_metadata (Part 08 §2.7); the loaded model is the fallback.
        model_performance=repo.active_model() or model_performance(predictor),
    )
