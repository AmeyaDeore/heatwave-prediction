"""GET /analytics (Part 07 §3.5, Part 14) and GET /weather (Part 07 §3.2).

Counting rules, stated once here and returned in the response (``event_rule``):

- A **region-day** is one region on one calendar date. Its class is the class of the
  most recent prediction made *for that date* (a later forecast supersedes an
  earlier one; days are never double-counted across overlapping runs).
- A **heatwave event** is a region-day whose class is HEATWAVE or SEVERE_HEATWAVE,
  the same daily unit as the IMD labelling rule the model was trained on (Part 03).
- The **temperature trend** takes, per date, an observation over a forecast, then
  the most recently fetched reading.

Model performance is static per deployed model version, read from model_metadata
(written at startup from Part 05's evaluation report), never recomputed.
"""

from collections import Counter
from datetime import date, timedelta
from statistics import mean

from heatwave_api.db.repository import FEATURE_FIELDS, Repository
from heatwave_api.errors import ApiError
from heatwave_api.predictions import resolve_region, summary
from heatwave_api.reference import region_dict
from heatwave_api.services import Services
from heatwave_ml.explainability.summary import format_value
from heatwave_ml.features import RISK_CLASS_LABELS

PERIOD_DAYS = {"week": 7, "month": 30, "season": 122}  # season: Mar-Jun, India's hot season
EVENT_RULE = (
    "One event = one region-day whose most recent prediction for that date was "
    "HEATWAVE or SEVERE_HEATWAVE."
)


def _best_per_date(snapshots: list[dict]) -> dict[tuple[str, str], dict]:
    best: dict[tuple[str, str], dict] = {}
    for s in snapshots:
        key = (s["region_id"], s["date"])
        rank = (s["kind"] == "ACTUAL", s["fetched_at"], s["id"])
        current = best.get(key)
        if current is None or rank > (
            current["kind"] == "ACTUAL",
            current["fetched_at"],
            current["id"],
        ):
            best[key] = s
    return best


def temperature_trend(
    services: Services, repo: Repository, start: date, end: date, region_id: str | None
) -> list[dict]:
    best = _best_per_date(repo.snapshots_between(start.isoformat(), end.isoformat(), region_id))
    by_date: dict[str, list[dict]] = {}
    for (_, day), s in sorted(best.items(), key=lambda kv: kv[0][1]):
        by_date.setdefault(day, []).append(s)
    points = []
    for day, rows in by_date.items():
        if region_id:
            s = rows[0]
            tmax, normal, deviation = s["tmax_c"], s["normal_tmax_c"], s["temp_deviation_c"]
            if normal is not None:
                zone = services.reference.display_region(region_id)["zone"]
                hw, severe = services.reference.thresholds(zone, normal)
            else:
                hw = severe = None
        else:  # all regions: the mean reading; thresholds differ per region, so none
            tmax, normal, deviation = (
                _mean([r[k] for r in rows]) for k in ("tmax_c", "normal_tmax_c", "temp_deviation_c")
            )
            hw = severe = None
        points.append(
            {
                "date": day,
                "kind": "ACTUAL" if all(r["kind"] == "ACTUAL" for r in rows) else "FORECAST",
                "tmax_c": tmax,
                "normal_tmax_c": normal,
                "temp_deviation_c": deviation,
                "heatwave_threshold_c": hw,
                "severe_threshold_c": severe,
                "above_heatwave_threshold": (tmax >= hw)
                if hw is not None and tmax is not None
                else None,
            }
        )
    return points


def _mean(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return round(mean(present), 2) if present else None


def risk_distribution(rows: list[dict]) -> dict:
    counts = Counter(r["risk_class"] for r in rows)
    total = sum(counts.values())
    return {
        "total_region_days": total,
        "classes": [
            {
                "risk_class": c,
                "label": label,
                "region_days": counts.get(c, 0),
                "pct": round(100 * counts.get(c, 0) / total, 1) if total else 0.0,
            }
            for c, label in RISK_CLASS_LABELS.items()
        ],
    }


def _month_start(day: date, months_back: int) -> date:
    index = day.year * 12 + day.month - 1 - months_back
    return date(index // 12, index % 12 + 1, 1)


def heatwave_events(repo: Repository, end: date, months: int, region_id: str | None) -> list[dict]:
    first = _month_start(end, months - 1)
    rows = repo.daily_classes(first.isoformat(), end.isoformat(), region_id)
    out = []
    for i in range(months):
        m = _month_start(end, months - 1 - i)
        key = f"{m:%Y-%m}"
        in_month = Counter(r["risk_class"] for r in rows if r["target_date"].startswith(key))
        hw, severe = in_month.get("HEATWAVE", 0), in_month.get("SEVERE_HEATWAVE", 0)
        out.append(
            {
                "month": key,
                "heatwave_days": hw,
                "severe_heatwave_days": severe,
                "event_days": hw + severe,
            }
        )
    return out


def model_performance(repo: Repository) -> dict | None:
    m = repo.active_model()
    if m is None:
        return None
    return {
        "model_version": m["model_version"],
        "model_family": m["model_family"],
        "explainer_id": m["explainer_id"],
        "evaluation_id": m["evaluation_id"],
        "policy_version": m["policy_version"],
        "report": m["report"],
        "test_rows": m["test_rows"],
        "precision": m["precision_macro"],
        "recall": m["recall_macro"],
        "f1": m["f1_macro"],
        "accuracy": m["accuracy"],
        "confidence": m["mean_confidence"],
        "top_label_ece": m["top_label_ece"],
        "per_class": m["per_class"],
        "deployed_at": m["deployed_at"],
    }


def analytics(
    services: Services,
    repo: Repository,
    *,
    region_id: str | None,
    period: str,
    end: date | None,
    months: int,
) -> dict:
    region = region_dict(resolve_region(services, region_id)) if region_id else None
    end = end or services.weather.today()
    days = PERIOD_DAYS[period]
    start = end - timedelta(days=days - 1)
    return {
        "region": region,
        "period": {"name": period, "start": start, "end": end, "days": days},
        "temperature_trend": temperature_trend(services, repo, start, end, region_id),
        "risk_distribution": risk_distribution(
            repo.daily_classes(start.isoformat(), end.isoformat(), region_id)
        ),
        "heatwave_events": heatwave_events(repo, end, months, region_id),
        "event_rule": EVENT_RULE,
        "model_performance": model_performance(repo),
    }


# -- current weather --------------------------------------------------------------------


def _current(snapshot: dict) -> dict:
    values = {k: snapshot[k] for k in FEATURE_FIELDS}
    return {
        "date": snapshot["date"],
        "kind": snapshot["kind"],
        "source": snapshot["source"],
        "issued_at": snapshot["issued_at"],
        "fetched_at": snapshot["fetched_at"],
        **values,
        "display": {k: format_value(k, v) for k, v in values.items() if v is not None},
    }


def current_weather(services: Services, repo: Repository, region_id: str | None) -> dict:
    """Today's conditions per region, plus its latest prediction. One region failing
    upstream does not fail the others: its item carries the error instead."""
    if region_id is not None:
        regions = [resolve_region(services, region_id)]
    else:
        regions = list(services.reference.regions.values())
    latest = repo.latest_run_ids([r.id for r in regions])
    runs = repo.run_summaries(list(latest.values()))
    today = services.weather.today().isoformat()
    items, failures = [], []
    for region in regions:
        item = {
            "region": region_dict(region),
            "current": None,
            "latest_prediction": None,
            "error": None,
        }
        if region.id in latest:
            item["latest_prediction"] = summary(runs[latest[region.id]])
        try:
            services.weather.forecast(repo, region)  # refreshes the stored forecast if stale
            snapshot = repo.best_snapshot(region.id, today)
            item["current"] = _current(snapshot) if snapshot else None
        except ApiError as exc:
            if region_id is not None:
                raise
            failures.append(exc)
            item["error"] = {
                "code": exc.code,
                "category": exc.category,
                "message": exc.message,
                "details": exc.details,
            }
        items.append(item)
    if failures and len(failures) == len(regions):
        raise failures[0]  # nothing to show: report the upstream failure itself
    return {"items": items}
