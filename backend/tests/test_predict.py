"""POST /api/v1/predict and the prediction reads, against a fake model and forecast."""

from datetime import timedelta

import pytest
from api_support import NOW, heat

from heatwave_api.errors import UpstreamBadResponse, UpstreamUnavailable

PREDICT = "/api/v1/predict"
FACTOR_FEATURES = {
    "tmax_c",
    "normal_tmax_c",
    "rh_pct",
    "wind_ms",
    "solar_mj_m2",
    "precip_mm",
    "temp_deviation_c",
}


def test_forecast_prediction_carries_every_contract_field(client, fakes):
    fakes.forecast.tmax["mumbai"] = [33.0, 34.0, 41.5, 36.0]  # lead 2 is the hot one
    response = client.post(PREDICT, json={"region_id": "mumbai"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "success" and body["error"] is None
    assert body["meta"]["api_version"] == "v1" and body["meta"]["request_id"]
    data = body["data"]

    tomorrow = NOW.date() + timedelta(days=1)
    assert data["forecast_window"] == {
        "start": tomorrow.isoformat(),
        "end": (tomorrow + timedelta(days=2)).isoformat(),
        "days": 3,
        "label": "Next 3 days",
    }
    assert [d["lead_days"] for d in data["daily"]] == [1, 2, 3]
    # The headline is the riskiest day, and every top-level field is that day's.
    assert data["peak_date"] == (NOW.date() + timedelta(days=2)).isoformat()
    peak = data["daily"][1]
    assert data["risk_class"] == peak["risk_class"] == "SEVERE_HEATWAVE"
    assert data["risk_label"] == "Severe Heatwave"
    assert data["confidence"] == data["probabilities"]["SEVERE_HEATWAVE"] == 0.9
    assert data["explanation"] == peak["explanation"]
    assert data["inputs"] == peak["inputs"]

    # Explainability is part of the same response, for every day (CLAUDE.md).
    for day in data["daily"]:
        factors = day["explanation"]["factors"]
        assert {f["feature"] for f in factors} == FACTOR_FEATURES
        assert [f["rank"] for f in factors] == list(range(1, 8))
        assert day["explanation"]["summary"].startswith("The model predicts")
    assert data["explanation"]["factors"][0]["feature"] == "temp_deviation_c"

    # The dashboard's metric cards read these, never recompute them.
    assert data["inputs"]["tmax_c"]["value"] == 41.5
    assert data["inputs"]["tmax_c"]["display_value"] == "41.5 °C"
    assert data["inputs"]["wind_ms"]["value"] == pytest.approx(2.24, abs=0.01)  # 10 m -> 2 m
    deviation = data["inputs"]["temp_deviation_c"]["value"]
    assert data["inputs"]["normal_tmax_c"]["value"] == pytest.approx(41.5 - deviation, abs=0.01)

    assert [a["code"] for a in data["recommended_actions"]][:2] == [
        "SEVERE_WARNING_ALL_CHANNELS",
        "ACTIVATE_COOLING_CENTRES_EXTENDED",
    ]
    assert data["actions_version"] == "ACT-v1"
    assert data["source"]["weather"] == "open_meteo_forecast" and data["source"]["fetched_at"]
    assert data["model"] == {
        "model_version": "xgboost-test",
        "explainer_id": "xgboost-test+shap.0000",
    }
    assert response.headers["Location"] == f"/api/v1/predictions/{data['prediction_id']}"


def test_a_stored_prediction_reads_back_identically(client):
    created = client.post(PREDICT, json={"region_id": "kurla"}).json()["data"]
    fetched = client.get(f"/api/v1/predictions/{created['prediction_id']}").json()["data"]
    assert fetched == created


def test_peak_day_ties_go_to_the_higher_risk_then_the_earlier_day(client, fakes):
    fakes.forecast.tmax["colaba"] = [33.0] * 4  # three identical NORMAL days
    data = client.post(PREDICT, json={"region_id": "colaba"}).json()["data"]
    assert data["risk_class"] == "NORMAL"
    assert data["peak_date"] == data["daily"][0]["date"]
    assert [a["code"] for a in data["recommended_actions"]] == [
        "ROUTINE_MONITORING",
        "KEEP_PLAN_READY",
    ]


def test_forecast_days_narrows_the_window(client):
    data = client.post(PREDICT, json={"region_id": "mumbai", "forecast_days": 1}).json()["data"]
    assert len(data["daily"]) == 1
    assert data["forecast_window"]["label"] == "Next day"


def test_the_stored_forecast_is_reused_until_it_is_stale(client, fakes):
    client.post(PREDICT, json={"region_id": "mumbai"})
    client.post(PREDICT, json={"region_id": "mumbai"})
    client.get("/api/v1/weather?region_id=mumbai")
    assert fakes.forecast.calls == 1
    fakes.clock.now = NOW + timedelta(minutes=61)
    client.post(PREDICT, json={"region_id": "mumbai"})
    assert fakes.forecast.calls == 2


def test_caller_supplied_conditions(client, fakes):
    response = client.post(
        PREDICT,
        json={
            "region_id": "andheri",
            "conditions": [heat(0, 42.0), heat(1, 30.0, rh_pct=80, wind_ms=4, wind_height_m=2)],
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert fakes.forecast.calls == 0
    assert data["source"] == {"weather": "client", "issued_at": None, "fetched_at": None}
    assert [d["lead_days"] for d in data["daily"]] == [0, 1]
    assert data["peak_date"] == NOW.date().isoformat()
    # Missing humidity was imputed, and the response says so wherever it shows.
    assert data["daily"][0]["inputs"]["rh_pct"]["imputed"] is True
    assert data["daily"][1]["inputs"]["rh_pct"]["imputed"] is False
    assert data["daily"][1]["inputs"]["wind_ms"]["value"] == 4.0  # already at 2 m


@pytest.mark.parametrize(
    "body, where",
    [
        ({"region_id": "mumbai", "conditions": [heat(0, 40.0, wind_ms=3)]}, "conditions"),
        ({"region_id": "mumbai", "forecast_days": 2, "conditions": [heat(0)]}, ""),
        ({"region_id": "mumbai", "conditions": [heat(0), heat(0)]}, ""),
        ({"region_id": "mumbai", "conditions": [heat(0, 75.0)]}, "tmax_c"),
        ({"region_id": "mumbai", "conditions": [heat(0, rh_pct=120)]}, "rh_pct"),
        ({"region_id": "mumbai", "conditions": []}, "conditions"),
        ({"region_id": "mumbai", "forecast_days": 4}, "forecast_days"),
        ({"region_id": "mumbai", "surprise": 1}, "surprise"),
        ({"region_id": "Mumbai Central!"}, "region_id"),
        ({}, "region_id"),
    ],
)
def test_invalid_input_is_a_clear_422(client, fakes, body, where):
    response = client.post(PREDICT, json=body)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and error["category"] == "client"
    assert any(where in ".".join(map(str, d["loc"])) for d in error["details"])
    assert fakes.model.calls == 0  # rejected before touching the model


def test_unknown_region(client):
    response = client.post(PREDICT, json={"region_id": "atlantis"})
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "UNKNOWN_REGION"
    assert "mumbai" in error["details"]["known_regions"]


@pytest.mark.parametrize(
    "exc, status, code",
    [
        (UpstreamUnavailable("down"), 503, "WEATHER_SOURCE_UNAVAILABLE"),
        (UpstreamBadResponse("garbage"), 502, "WEATHER_SOURCE_ERROR"),
    ],
)
def test_upstream_failures_are_reported_as_upstream(client, fakes, exc, status, code, repo):
    fakes.forecast.error = exc
    response = client.post(PREDICT, json={"region_id": "mumbai"})
    assert response.status_code == status
    assert response.json()["error"]["category"] == "upstream"
    assert response.json()["error"]["code"] == code
    assert repo.latest_run_ids() == {}  # nothing half-stored


def test_a_forecast_missing_a_day_is_an_upstream_error(client, fakes):
    fakes.forecast.tmax["mumbai"] = [33.0, None, 34.0, 35.0]
    response = client.post(PREDICT, json={"region_id": "mumbai"})
    assert response.status_code == 502
    assert "maximum temperature" in response.json()["error"]["message"]


def test_a_model_failure_is_internal_and_leaks_nothing(client, fakes):
    fakes.model.fail = True
    response = client.post(PREDICT, json={"region_id": "mumbai"})
    assert response.status_code == 500
    error = response.json()["error"]
    assert (error["code"], error["category"]) == ("PREDICTION_FAILED", "internal")
    assert "secret" not in response.text and "Traceback" not in response.text


def test_latest_prediction_per_region(client):
    first = client.post(PREDICT, json={"region_id": "mumbai"}).json()["data"]
    second = client.post(PREDICT, json={"region_id": "mumbai", "forecast_days": 2}).json()["data"]
    client.post(PREDICT, json={"region_id": "kurla"})
    data = client.get("/api/v1/predictions/latest").json()["data"]
    by_region = {p["region"]["id"]: p for p in data["items"]}
    assert set(by_region) == {"mumbai", "kurla"}
    # Both runs land in the same clock second; insertion order still decides.
    assert by_region["mumbai"]["prediction_id"] == second["prediction_id"]
    assert first["prediction_id"] != second["prediction_id"]
    assert data["missing_regions"] == ["andheri", "dharavi", "colaba"]

    one = client.get("/api/v1/predictions/latest?region_id=kurla").json()["data"]
    assert [p["region"]["id"] for p in one["items"]] == ["kurla"]


def test_unknown_prediction_id(client):
    response = client.get(f"/api/v1/predictions/{'0' * 32}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PREDICTION_NOT_FOUND"
    assert client.get("/api/v1/predictions/not-an-id").status_code == 422


def test_predict_is_rate_limited(make_client):
    client = make_client(rate_limit_predict="2/minute")
    for _ in range(2):
        assert client.post(PREDICT, json={"region_id": "mumbai"}).status_code == 201
    response = client.post(PREDICT, json={"region_id": "mumbai"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= int(response.headers["Retry-After"]) <= 60
