"""The real production model and explainer behind the real API.

Skipped on a fresh clone until the git-ignored bundle is rebuilt with
`uv run heatwave-train run` (training is reproducible), like Part 06's own tests.
"""

import statistics
import time

import pytest
from api_support import FakeForecast, heat
from fastapi.testclient import TestClient

from heatwave_api.inference import ModelService
from heatwave_api.main import create_app
from heatwave_api.notifications import MockNotifier
from heatwave_api.services import assemble_services
from heatwave_ml.registry import ModelRegistry

LATENCY_BUDGET_P95_MS = 500  # config/model_selection.yaml gates.max_p95_request_ms


@pytest.fixture(scope="module")
def model():
    from heatwave_api.config import Settings

    settings = Settings(_env_file=None)
    try:
        return ModelService.load(settings, ["mumbai"])
    except Exception as exc:
        pytest.skip(f"production model or explainer not available here: {exc}")


@pytest.fixture
def real_client(settings, model, fakes):
    def factory(s):
        return assemble_services(
            s,
            model=model,
            provider=FakeForecast(),
            notifier=MockNotifier(),
            weather_clock=fakes.clock,
        )

    with TestClient(create_app(settings, factory, configure_logs=False)) as client:
        yield client


def test_the_service_serves_the_registry_production_model(model, settings):
    pointer = ModelRegistry(settings.model_registry_dir, settings.runs_dir).production()
    assert model.model_version == pointer["model_version"]
    assert model.explainer_id.startswith(pointer["model_version"] + "+shap.")
    meta = model.metadata()
    assert meta["f1_macro"] == pointer["evaluation"]["test_metrics"]["f1_macro"]
    assert meta["mean_confidence"] == pointer["evaluation"]["calibration"]["mean_confidence"]


def test_an_extreme_day_is_severe_and_explained_by_temperature(real_client):
    response = real_client.post(
        "/api/v1/predict",
        json={
            "region_id": "mumbai",
            "conditions": [heat(1, 43.0, rh_pct=40, wind_ms=2, wind_height_m=10, solar_mj_m2=25)],
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["risk_class"] == "SEVERE_HEATWAVE"
    top = data["explanation"]["factors"][0]
    assert top["feature"] in {"temp_deviation_c", "tmax_c"} and top["direction"] == "increases_risk"
    assert data["explanation"]["summary"].startswith("The model predicts Severe Heatwave")
    total = sum(abs(f["share_pct"]) for f in data["explanation"]["factors"])
    assert total == pytest.approx(100, abs=0.5)
    # Additivity survives the API: baseline + contributions = output.
    contributions = sum(f["contribution"] for f in data["explanation"]["factors"])
    assert data["explanation"]["baseline"] + contributions == pytest.approx(
        data["explanation"]["output"], abs=7 * 5e-5 + 1e-4
    )
    assert real_client.get(f"/api/v1/predictions/{data['prediction_id']}").json()["data"] == data


def test_end_to_end_predict_latency_is_within_budget(real_client):
    """POST /predict for 3 forecast days: forecast lookup, features, model, 3 SHAP
    explanations, the database write and the response, measured through the app."""
    real_client.post("/api/v1/predict", json={"region_id": "kurla"})  # warm the cache
    times = []
    for _ in range(30):
        started = time.perf_counter()
        response = real_client.post("/api/v1/predict", json={"region_id": "kurla"})
        times.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 201
    p95 = statistics.quantiles(times, n=20)[-1]
    print(f"\nPOST /predict (3 days): p50 {statistics.median(times):.1f} ms, p95 {p95:.1f} ms")
    # The test clock is fixed, so every call after the first reuses the stored forecast.
    assert p95 < LATENCY_BUDGET_P95_MS
