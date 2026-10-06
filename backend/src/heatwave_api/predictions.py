"""POST /predict and the prediction read endpoints: weather in, prediction run out.

A run is the 1-3 day window for one region. Every day gets its own prediction and
its own SHAP explanation. The run's headline (the top-level fields of the response)
is the peak day: the highest risk class, then the higher 1 - P(NORMAL), then the
earlier date. Stored runs and fresh ones go through the same ``payload`` function,
so GET returns exactly what POST returned.
"""

import logging
import uuid
from datetime import date

import pandas as pd

from heatwave_api.db import utcnow
from heatwave_api.db.repository import Repository
from heatwave_api.errors import (
    NotFound,
    PredictionFailed,
    UnknownRegion,
    UpstreamBadResponse,
    ValidationFailed,
)
from heatwave_api.reference import MAX_FORECAST_DAYS
from heatwave_api.schemas import PredictRequest
from heatwave_api.services import Services
from heatwave_ml.features import FEATURE_COLUMNS, RISK_CLASS_LABELS
from heatwave_ml.ingestion.regions import Region

log = logging.getLogger(__name__)

RISK_ORDER = {"NORMAL": 0, "HEATWAVE": 1, "SEVERE_HEATWAVE": 2}
# Feature values travel through prediction_factors; these are the snapshot columns.
CLIENT_SOURCE, FORECAST_SOURCE = "client", "open_meteo_forecast"


def resolve_region(services: Services, region_id: str) -> Region:
    region = services.reference.region(region_id)
    if region is None:
        raise UnknownRegion(
            f"Unknown region '{region_id}'.",
            details={"known_regions": sorted(services.reference.regions)},
        )
    return region


# -- weather in -------------------------------------------------------------------------


def _client_rows(region: Region, request: PredictRequest, today: date) -> list[dict]:
    rows = []
    for c in sorted(request.conditions, key=lambda c: c.date):
        rows.append(
            {
                "region_id": region.id,
                "date": c.date.isoformat(),
                "lead_days": (c.date - today).days,
                "weather_snapshot_id": None,
                "tmax_c": c.tmax_c,
                "rh_pct": c.rh_pct,
                "wind_ms": c.wind_ms,
                # With no wind value the height is irrelevant, but build_features insists.
                "wind_height_m": c.wind_height_m if c.wind_ms is not None else 2,
                "solar_mj_m2": c.solar_mj_m2,
                "precip_mm": c.precip_mm,
            }
        )
    return rows


def _forecast_rows(
    services: Services, repo: Repository, region: Region, days: int
) -> tuple[list[dict], dict]:
    snapshots = services.weather.forecast(repo, region)
    chosen = [s for s in snapshots if 1 <= s["lead_days"] <= days]
    if len(chosen) < days:
        raise UpstreamBadResponse(
            f"The forecast for {region.name} covers only {len(chosen)} of the next {days} days.",
            details={"source": FORECAST_SOURCE},
        )
    if any(s["tmax_c"] is None for s in chosen):
        raise UpstreamBadResponse(
            f"The forecast for {region.name} has no maximum temperature for some days.",
            details={"source": FORECAST_SOURCE},
        )
    rows = [
        {
            "region_id": region.id,
            "date": s["date"],
            "lead_days": s["lead_days"],
            "weather_snapshot_id": s["id"],
            "tmax_c": s["tmax_c"],
            "rh_pct": s["rh_pct"],
            # Stored snapshots are already at the 2 m reference height.
            "wind_ms": s["wind_ms"],
            "wind_height_m": 2,
            "solar_mj_m2": s["solar_mj_m2"],
            "precip_mm": s["precip_mm"],
        }
        for s in chosen
    ]
    source = {"issued_at": chosen[0]["issued_at"], "fetched_at": chosen[0]["fetched_at"]}
    return rows, source


# -- the run ----------------------------------------------------------------------------


def _day_record(row: dict, result: dict, run_id: str, created_at: str) -> dict:
    p = result["prediction"]
    e = p["explanation"]
    factors = [{k: f[k] for k in f} | {"imputed": int(f["imputed"])} for f in e["factors"]]
    used = {f["feature"]: f["value"] for f in factors}  # after imputation
    return {
        "run_id": run_id,
        "region_id": row["region_id"],
        "weather_snapshot_id": row["weather_snapshot_id"],
        "target_date": row["date"],
        "lead_days": row["lead_days"],
        "created_at": created_at,
        **{name: used[name] for name in FEATURE_COLUMNS},
        "risk_class": p["risk_class"],
        "confidence": p["confidence"],
        "p_normal": p["probabilities"]["NORMAL"],
        "p_heatwave": p["probabilities"]["HEATWAVE"],
        "p_severe_heatwave": p["probabilities"]["SEVERE_HEATWAVE"],
        "target_class": e["target_class"],
        "quantity": e["quantity"],
        "explained": e["explained"],
        "baseline": e["baseline"],
        "output": e["output"],
        "summary": e["summary"],
        "model_version": e["model_version"],
        "explainer_id": e["explainer_id"],
        "factors": factors,
    }


def peak_day(days: list[dict]) -> dict:
    return max(
        days,
        key=lambda d: (
            RISK_ORDER[d["risk_class"]],
            round(1 - d["p_normal"], 4),
            -date.fromisoformat(d["target_date"]).toordinal(),
        ),
    )


def run_prediction(services: Services, repo: Repository, request: PredictRequest) -> dict:
    region = resolve_region(services, request.region_id)
    today = services.weather.today()
    if request.conditions is not None:
        rows, source = _client_rows(region, request, today), {"issued_at": None, "fetched_at": None}
        source_name = CLIENT_SOURCE
    else:
        days = request.forecast_days or MAX_FORECAST_DAYS
        rows, source = _forecast_rows(services, repo, region, days)
        source_name = FORECAST_SOURCE

    try:
        results = services.model.predict(pd.DataFrame(rows))
    except ValueError as exc:  # build_features' unit checks: the input, not the model
        raise ValidationFailed(f"The weather values cannot be used: {exc}") from exc
    except Exception as exc:
        log.exception("prediction failed", extra={"region_id": region.id})
        raise PredictionFailed("The model could not produce a prediction.") from exc

    run_id = uuid.uuid4().hex
    created_at = utcnow()
    days = [_day_record(r, res, run_id, created_at) for r, res in zip(rows, results, strict=True)]
    peak = peak_day(days)
    run = {
        "id": run_id,
        "region_id": region.id,
        "created_at": created_at,
        "window_start": days[0]["target_date"],
        "window_end": days[-1]["target_date"],
        "source": source_name,
        "issued_at": source["issued_at"],
        "fetched_at": source["fetched_at"],
        "peak_date": peak["target_date"],
        "risk_class": peak["risk_class"],
        "confidence": peak["confidence"],
        "model_version": peak["model_version"],
        "explainer_id": peak["explainer_id"],
    }
    repo.insert_prediction_run(run, days)
    return payload(services, run, days)


# -- payloads ---------------------------------------------------------------------------


def forecast_window(run: dict) -> dict:
    """A forecast run always covers lead days 1..N; a client run covers its own dates."""
    start, end = date.fromisoformat(run["window_start"]), date.fromisoformat(run["window_end"])
    days = (end - start).days + 1
    if run["source"] == FORECAST_SOURCE:
        label = "Next day" if days == 1 else f"Next {days} days"
    elif start == end:
        label = f"{start:%d %b %Y}"
    else:
        label = f"{start:%d %b} - {end:%d %b %Y}"
    return {"start": run["window_start"], "end": run["window_end"], "days": days, "label": label}


def _day_payload(day: dict) -> dict:
    factors = [
        {k: f[k] for k in f if k != "prediction_id"} | {"imputed": bool(f["imputed"])}
        for f in day["factors"]
    ]
    by_feature = {f["feature"]: f for f in factors}
    return {
        "date": day["target_date"],
        "lead_days": day["lead_days"],
        "risk_class": day["risk_class"],
        "risk_label": RISK_CLASS_LABELS[day["risk_class"]],
        "confidence": day["confidence"],
        "probabilities": {
            "NORMAL": day["p_normal"],
            "HEATWAVE": day["p_heatwave"],
            "SEVERE_HEATWAVE": day["p_severe_heatwave"],
        },
        "inputs": {
            name: {k: by_feature[name][k] for k in ("label", "unit", "value", "display_value")}
            | {"imputed": by_feature[name]["imputed"]}
            for name in FEATURE_COLUMNS
        },
        "explanation": {
            "target_class": day["target_class"],
            "reference_class": "NORMAL",
            "quantity": day["quantity"],
            "explained": day["explained"],
            "baseline": day["baseline"],
            "output": day["output"],
            "factors": factors,
            "summary": day["summary"],
            "model_version": day["model_version"],
            "explainer_id": day["explainer_id"],
        },
    }


def payload(services: Services, run: dict, days: list[dict]) -> dict:
    daily = [_day_payload(d) for d in days]
    peak = next(d for d in daily if d["date"] == run["peak_date"])
    return {
        "prediction_id": run["id"],
        "region": services.reference.display_region(run["region_id"]),
        "created_at": run["created_at"],
        "forecast_window": forecast_window(run),
        "peak_date": run["peak_date"],
        **{k: peak[k] for k in ("risk_class", "risk_label", "confidence", "probabilities")},
        "inputs": peak["inputs"],
        "explanation": peak["explanation"],
        "recommended_actions": services.actions.recommend(
            peak["risk_class"], peak["explanation"]["factors"]
        ),
        "actions_version": services.actions.version,
        "daily": daily,
        "source": {
            "weather": run["source"],
            "issued_at": run["issued_at"],
            "fetched_at": run["fetched_at"],
        },
        "model": {"model_version": run["model_version"], "explainer_id": run["explainer_id"]},
    }


def summary(run: dict) -> dict:
    return {
        "prediction_id": run["id"],
        "created_at": run["created_at"],
        "forecast_window": forecast_window(run),
        "peak_date": run["peak_date"],
        "risk_class": run["risk_class"],
        "risk_label": RISK_CLASS_LABELS[run["risk_class"]],
        "confidence": run["confidence"],
    }


def stored_prediction(services: Services, repo: Repository, prediction_id: str) -> dict:
    run = repo.run(prediction_id)
    if run is None:
        raise NotFound(f"No prediction '{prediction_id}'.", code="PREDICTION_NOT_FOUND")
    return payload(services, run, run.pop("days"))


def latest_predictions(services: Services, repo: Repository, region_id: str | None) -> dict:
    if region_id is not None:
        resolve_region(services, region_id)
        wanted = [region_id]
    else:
        wanted = list(services.reference.regions)
    latest = repo.latest_run_ids(wanted)
    items = []
    for rid in wanted:
        if rid in latest:
            run = repo.run(latest[rid])
            items.append(payload(services, run, run.pop("days")))
    return {"items": items, "missing_regions": [r for r in wanted if r not in latest]}
