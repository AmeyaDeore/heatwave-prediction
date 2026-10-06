"""Test doubles and helpers for the backend tests (fixtures are in conftest.py).

Named api_support, not conftest, so it cannot collide with ml/tests/conftest.py
when the whole repository is collected in one pytest run. The fake model builds its
output with Part 06's own contract code (rank_factors, summarize, Explanation), so
its shape cannot drift from the real explainer's.
"""

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from heatwave_api.config import REPO_ROOT
from heatwave_api.errors import UpstreamUnavailable
from heatwave_api.weather import LOCAL_TZ
from heatwave_ml.explainability.explainer import Explanation, rank_factors
from heatwave_ml.explainability.summary import summarize
from heatwave_ml.features import FEATURE_COLUMNS, SeasonalNormals, build_features

NORMALS = SeasonalNormals.load(REPO_ROOT / "config" / "seasonal_normals.csv")
NOW = datetime(2026, 5, 10, 9, 30, tzinfo=LOCAL_TZ)  # a May morning in Mumbai
PASSWORD = "correct horse battery staple"  # pragma: allowlist secret
FILL = {"rh_pct": 65.0, "wind_ms": 2.5, "solar_mj_m2": 20.0, "precip_mm": 0.0}
WEIGHTS = {
    "temp_deviation_c": 0.8,
    "tmax_c": 0.3,
    "normal_tmax_c": -0.05,
    "rh_pct": 0.02,
    "wind_ms": -0.2,
    "solar_mj_m2": 0.05,
    "precip_mm": -0.1,
}
CENTRE = {
    "temp_deviation_c": 0.0,
    "tmax_c": 33.0,
    "normal_tmax_c": 33.0,
    "rh_pct": 65.0,
    "wind_ms": 2.5,
    "solar_mj_m2": 20.0,
    "precip_mm": 0.0,
}


class FakeModel:
    """Classifies with the IMD departure thresholds and explains with fixed weights."""

    model_version = "xgboost-test"
    explainer_id = "xgboost-test+shap.0000"
    model_family = "xgboost"
    normals = NORMALS

    def __init__(self):
        self.calls = 0
        self.fail = False

    def metadata(self) -> dict:
        return {
            "model_version": self.model_version,
            "model_family": self.model_family,
            "model_sha256": "0" * 64,
            "explainer_id": self.explainer_id,
            "evaluation_id": "20260929T081440Z-test",
            "policy_version": "SEL-v1",
            "report": "ml/registry/evaluations/test/report.md",
            "test_rows": 746,
            "accuracy": 0.94,
            "precision_macro": 0.85,
            "recall_macro": 0.91,
            "f1_macro": 0.88,
            "mean_confidence": 0.97,
            "top_label_ece": 0.03,
            "per_class": {"NORMAL": {"precision": 0.99, "recall": 0.96, "f1": 0.97}},
        }

    def predict(self, raw: pd.DataFrame) -> list[dict]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("explainer exploded at /secret/path/model.json")
        features = build_features(raw, self.normals)
        out = []
        for _, row in features.iterrows():
            imputed = row[list(FEATURE_COLUMNS)].isna()
            values = row[list(FEATURE_COLUMNS)].astype(float).fillna(pd.Series(FILL))
            deviation, tmax = values["temp_deviation_c"], values["tmax_c"]
            if tmax >= 37 and deviation >= 6.5:
                risk, probs = "SEVERE_HEATWAVE", (0.02, 0.08, 0.90)
            elif tmax >= 37 and deviation >= 4.5:
                risk, probs = "HEATWAVE", (0.10, 0.80, 0.10)
            else:
                risk, probs = "NORMAL", (0.95, 0.04, 0.01)
            contributions = np.array(
                [WEIGHTS[c] * (values[c] - CENTRE[c]) for c in FEATURE_COLUMNS]
            )
            factors = rank_factors(contributions, values, imputed)
            probabilities = dict(zip(("NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"), probs, strict=True))
            target = "HEATWAVE" if risk == "NORMAL" else risk
            e = Explanation(
                risk_class=risk,
                probabilities=probabilities,
                target_class=target,
                reference_class="NORMAL",
                quantity="log_odds",
                explained=f"log(P({target}) / P(NORMAL))",
                baseline=-3.0,
                output=round(-3.0 + float(contributions.sum()), 4),
                factors=factors,
                summary=summarize(risk, probabilities, factors),
                model_version=self.model_version,
                explainer_id=self.explainer_id,
            )
            out.append({"features": row.to_dict(), "prediction": e.to_dict()})
        return out


class FakeForecast:
    """Open-Meteo-shaped frames. ``tmax`` per region, default 33 °C every day."""

    name = "open_meteo_forecast"

    def __init__(self):
        self.calls = 0
        self.tmax: dict[str, list[float]] = {}
        self.fail_regions: set[str] = set()
        self.error: Exception | None = None

    def forecast(self, region, today, days):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if region.id in self.fail_regions:
            raise UpstreamUnavailable("The weather forecast service is not reachable right now.")
        temps = self.tmax.get(region.id, [33.0] * (days + 1))
        return pd.DataFrame(
            {
                "region_id": region.id,
                "date": pd.to_datetime([today + timedelta(days=i) for i in range(days + 1)]),
                "tmax_c": temps,
                "rh_pct": 70.0,
                "wind_ms": 3.0,
                "solar_mj_m2": 21.0,
                "precip_mm": 0.0,
                "lead_days": list(range(days + 1)),
                "issued_at": NOW.astimezone(UTC).isoformat(),
                "wind_height_m": 10,
            }
        )


class Clock:
    def __init__(self, now: datetime = NOW):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def new_alert(**overrides) -> dict:
    return {
        "client_request_id": str(uuid.uuid4()),
        "region_id": "mumbai",
        "severity": "SEVERE_HEATWAVE",
        "message": "SEVERE HEATWAVE ALERT - MUMBAI. Avoid prolonged outdoor exposure.",
        "channels": ["PUBLIC_MOBILE_ALERT", "GOVERNMENT_PORTAL", "EMERGENCY_SERVICES"],
    } | overrides


def heat(day_offset: int, tmax: float = 42.0, **extra) -> dict:
    """A client condition for NOW's date + day_offset."""
    return {"date": (NOW.date() + timedelta(days=day_offset)).isoformat(), "tmax_c": tmax} | extra
