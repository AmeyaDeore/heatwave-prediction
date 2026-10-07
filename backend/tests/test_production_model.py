"""The API on the real production model, explainer and pipeline weather file.

Skipped on a fresh clone until `heatwave-train run` has produced the (git-ignored) bundles.
"""

import pytest
from fastapi.testclient import TestClient

from heatwave_api.app import create_app
from heatwave_api.config import Settings
from heatwave_ml.features import FEATURE_COLUMNS

settings = Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None)

pytestmark = pytest.mark.skipif(
    not (settings.model_artifact_dir / "runs").exists()
    or not settings.weather_features_file.exists(),
    reason="production bundle or weather file not present",
)


@pytest.fixture(scope="module")
def real():
    with TestClient(create_app(settings)) as c:
        yield c


def test_the_service_starts_and_is_ready_on_the_production_model(real):
    data = real.get("/api/v1/health/ready").json()["data"]
    assert data["ready"] is True
    assert "+shap." in data["explainer_id"]


def test_real_prediction_has_all_seven_ranked_factors_and_matches_the_contract(real):
    r = real.post("/api/v1/predict", json={"region_id": "mumbai", "lead_days": 1})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["risk_class"] in {"NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"}
    assert sum(d["probabilities"].values()) == pytest.approx(1.0, abs=1e-3)
    assert d["confidence"] == max(d["probabilities"].values())
    factors = d["explanation"]["factors"]
    assert sorted(f["feature"] for f in factors) == sorted(FEATURE_COLUMNS)
    magnitudes = [abs(f["contribution"]) for f in factors]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert sum(abs(f["share_pct"]) for f in factors) == pytest.approx(100, abs=0.5)
    assert d["explanation"]["summary"]
    assert set(d["inputs"]) == set(FEATURE_COLUMNS)


def test_the_explanation_is_the_part_06_contract_unchanged(real):
    d = real.post("/api/v1/predict", json={"region_id": "colaba"}).json()["data"]
    explanation = d["explanation"]
    assert explanation["baseline"] + sum(f["contribution"] for f in explanation["factors"]) == (
        pytest.approx(explanation["output"], abs=1e-3)
    )


def test_prediction_latency_is_inside_part_05s_budget(real):
    import time

    real.post("/api/v1/predict", json={"region_id": "mumbai"})  # warm-up
    times = []
    for region in ("mumbai", "kurla", "andheri", "dharavi", "colaba") * 3:
        started = time.perf_counter()
        assert real.post("/api/v1/predict", json={"region_id": region}).status_code == 200
        times.append((time.perf_counter() - started) * 1000)
    times.sort()
    assert times[int(len(times) * 0.95) - 1] < 500  # config/model_selection.yaml max_p95_request_ms


def test_weather_derived_fields_come_from_the_shared_feature_path(real):
    rows = real.get("/api/v1/weather").json()["data"]
    assert rows
    for row in rows:
        assert row["temp_deviation_c"] == pytest.approx(
            row["tmax_c"] - row["normal_tmax_c"], abs=0.01
        )


def test_analytics_reports_the_promoted_models_test_metrics(real):
    perf = real.get("/api/v1/analytics").json()["data"]["model_performance"]
    assert perf["f1_macro"] == 0.88088
    assert perf["labeling_rule_version"] == "IMD-HW-DAILY-v1"
