"""Test doubles: a fake model, weather source and notifier (no model, file or database needed)."""

from datetime import UTC, date, datetime, timedelta

from heatwave_api.errors import UpstreamUnavailable
from heatwave_api.notifier import DeliveryResult
from heatwave_api.predictor import PredictionResult, PredictorInfo
from heatwave_api.weather import WeatherReading

NOW = datetime.now(UTC)


def reading(region_id="mumbai", lead_days=0, tmax=41.0, issued_hours_ago=2, **kw) -> WeatherReading:
    return WeatherReading(
        region_id=region_id,
        date=date.today() + timedelta(days=lead_days),
        lead_days=lead_days,
        issued_at=NOW - timedelta(hours=issued_hours_ago),
        tmax_c=tmax,
        rh_pct=kw.get("rh_pct", 40.0),
        wind_ms=kw.get("wind_ms", 1.5),
        solar_mj_m2=kw.get("solar_mj_m2", 25.0),
        precip_mm=kw.get("precip_mm", 0.0),
    )


def factor(rank, feature, direction="increases_risk", share=40.0):
    return {
        "rank": rank,
        "feature": feature,
        "label": feature,
        "unit": "",
        "value": 1.0,
        "display_value": "1",
        "imputed": False,
        "contribution": 1.0 if direction == "increases_risk" else -1.0,
        "share_pct": share if direction == "increases_risk" else -share,
        "direction": direction,
    }


class FakePredictor:
    """Risk from tmax: >=45 SEVERE, >=40 HEATWAVE, else NORMAL. Factor order is configurable."""

    def __init__(self):
        self.info = PredictorInfo(
            model_version="fake-model-v1",
            explainer_id="fake-model-v1+shap.test",
            model_family="xgboost",
            labeling_rule_version="TEST-v1",
            evaluation={
                "evaluation_id": "eval-test",
                "policy_version": "SEL-test",
                "test_rows": 100,
                "test_metrics": {
                    "accuracy": 0.9,
                    "precision_macro": 0.8,
                    "recall_macro": 0.85,
                    "f1_macro": 0.82,
                    "per_class": {
                        "NORMAL": {"precision": 0.9, "recall": 0.9, "f1": 0.9, "support": 80},
                        "HEATWAVE": {"precision": 0.7, "recall": 0.8, "f1": 0.75, "support": 15},
                        "SEVERE_HEATWAVE": {
                            "precision": 0.8,
                            "recall": 0.9,
                            "f1": 0.85,
                            "support": 5,
                        },
                    },
                },
                "calibration": {"top_label_ece": 0.03, "mean_confidence": 0.95},
            },
        )
        self.factors = [factor(1, "temp_deviation_c"), factor(2, "tmax_c")]
        self.fail: Exception | None = None
        self.calls = 0

    def _risk(self, r):
        if r.tmax_c >= 45:
            return "SEVERE_HEATWAVE"
        return "HEATWAVE" if r.tmax_c >= 40 else "NORMAL"

    def inputs(self, r):
        return {
            "tmax_c": r.tmax_c,
            "normal_tmax_c": 34.0,
            "rh_pct": r.rh_pct,
            "wind_ms": r.wind_ms,
            "solar_mj_m2": r.solar_mj_m2,
            "precip_mm": r.precip_mm,
            "temp_deviation_c": round(r.tmax_c - 34.0, 2),
        }

    def predict(self, r):
        self.calls += 1
        if self.fail:
            raise self.fail
        risk = self._risk(r)
        probs = {"NORMAL": 0.05, "HEATWAVE": 0.05, "SEVERE_HEATWAVE": 0.05}
        probs[risk] = 0.9
        return PredictionResult(
            prediction={
                "risk_class": risk,
                "confidence": 0.9,
                "probabilities": probs,
                "explanation": {
                    "target_class": "HEATWAVE" if risk == "NORMAL" else risk,
                    "reference_class": "NORMAL",
                    "quantity": "log_odds",
                    "explained": "log(P(target) / P(NORMAL))",
                    "baseline": -4.0,
                    "output": 2.0,
                    "factors": list(self.factors),
                    "summary": f"The model predicts {risk}.",
                    "model_version": self.info.model_version,
                    "explainer_id": self.info.explainer_id,
                },
            },
            inputs=self.inputs(r),
        )


class FakeWeather:
    def __init__(self):
        self.rows = {
            (rid, lead): reading(rid, lead, tmax=41.0 + lead)
            for rid in ("mumbai", "kurla", "andheri", "dharavi", "colaba")
            for lead in range(4)
        }
        self.fail = False

    def reading(self, region_id, lead_days=0):
        if self.fail or (region_id, lead_days) not in self.rows:
            raise UpstreamUnavailable(f"No weather data for region '{region_id}'.")
        return self.rows[(region_id, lead_days)]

    def forecast(self, region_id):
        return [self.reading(region_id, lead) for lead in range(4)]

    def current(self):
        if self.fail:
            raise UpstreamUnavailable("down")
        return [r for (rid, lead), r in sorted(self.rows.items()) if lead == 0]


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.failing: dict[str, DeliveryResult | Exception] = {}

    def send(self, alert, channel_id):
        outcome = self.failing.get(channel_id)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            return outcome
        self.sent.append((alert.alert_id, channel_id))
        return DeliveryResult("NOTIFIED")
