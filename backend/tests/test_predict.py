from fakes import factor, reading

from heatwave_api.errors import PredictionFailed


def predict(client, **body):
    return client.post("/api/v1/predict", json={"region_id": "mumbai", **body})


def test_prediction_carries_the_full_contract(client):
    r = predict(client, lead_days=1)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["risk_class"] == "HEATWAVE"
    assert d["confidence"] == 0.9
    assert set(d["probabilities"]) == {"NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"}
    assert d["region"]["id"] == "mumbai"
    assert d["forecast_window"]["lead_days"] == 1
    assert d["forecast_window"]["horizon_days"] == 3
    assert d["inputs"]["tmax_c"] == 42.0
    assert d["prediction_id"].startswith("pred_")
    assert d["weather"]["stale"] is False


def test_prediction_returns_shap_factors_in_the_same_response(client):
    """CLAUDE.md core contract: every prediction carries its SHAP top factors."""
    explanation = predict(client).json()["data"]["explanation"]
    assert [f["rank"] for f in explanation["factors"]] == [1, 2]
    assert explanation["factors"][0]["feature"] == "temp_deviation_c"
    assert {"contribution", "share_pct", "direction", "display_value"} <= set(
        explanation["factors"][0]
    )
    assert explanation["model_version"] == "fake-model-v1"
    assert explanation["explainer_id"].startswith("fake-model-v1+shap")


def test_lead_days_defaults_to_today_and_is_bounded(client):
    assert predict(client).json()["data"]["forecast_window"]["lead_days"] == 0
    assert predict(client, lead_days=4).status_code == 422
    assert predict(client, lead_days=-1).status_code == 422


def test_unknown_region_is_a_404_before_any_scoring(client, predictor):
    r = predict(client, region_id="atlantis")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "UNKNOWN_REGION"
    assert predictor.calls == 0


def test_weather_source_failure_is_an_upstream_503(client, weather):
    weather.fail = True
    r = predict(client)
    assert r.status_code == 503
    assert r.json()["error"]["kind"] == "upstream"
    assert r.json()["error"]["code"] == "WEATHER_DATA_UNAVAILABLE"


def test_model_failure_is_an_internal_500_with_a_generic_message(client, predictor):
    predictor.fail = PredictionFailed("The model could not score these conditions.")
    r = predict(client)
    assert r.status_code == 500
    assert r.json()["error"]["kind"] == "internal"
    assert r.json()["error"]["code"] == "PREDICTION_FAILED"


def test_stale_weather_is_served_but_flagged(client, weather):
    weather.rows[("mumbai", 0)] = reading("mumbai", 0, issued_hours_ago=72)
    d = predict(client).json()["data"]
    assert d["weather"]["stale"] is True
    assert d["weather"]["age_hours"] >= 72


def test_prediction_is_stored_and_readable_back(client):
    made = predict(client).json()["data"]
    by_id = client.get(f"/api/v1/predictions/{made['prediction_id']}").json()["data"]
    latest = client.get("/api/v1/predictions/latest", params={"region_id": "mumbai"}).json()["data"]
    assert by_id == latest == made


def test_latest_prediction_404s_when_none_was_made(client):
    r = client.get("/api/v1/predictions/latest", params={"region_id": "kurla"})
    assert r.status_code == 404


def test_recommended_actions_are_deterministic_and_class_dependent(client, weather):
    weather.rows[("mumbai", 0)] = reading("mumbai", 0, tmax=48.0)
    weather.rows[("kurla", 0)] = reading("kurla", 0, tmax=30.0)
    severe = predict(client).json()["data"]["recommended_actions"]
    normal = predict(client, region_id="kurla").json()["data"]["recommended_actions"]
    assert severe == predict(client).json()["data"]["recommended_actions"]
    assert "Issue ward-level heat advisory" in severe
    assert any("emergency services" in a.lower() for a in severe)
    assert normal == ["Continue routine monitoring of the daily forecast"]


def test_a_top_humidity_factor_adds_humid_heat_guidance(client, predictor):
    predictor.factors = [factor(1, "rh_pct"), factor(2, "tmax_c")]
    actions = predict(client).json()["data"]["recommended_actions"]
    assert any("humid-heat" in a for a in actions)


def test_a_low_ranked_humidity_factor_does_not(client, predictor):
    predictor.factors = [
        factor(i, f) for i, f in enumerate(["tmax_c", "wind_ms", "solar_mj_m2"], 1)
    ]
    predictor.factors.append(factor(4, "rh_pct"))
    actions = predict(client).json()["data"]["recommended_actions"]
    assert not any("humid-heat" in a for a in actions)


def test_predict_is_rate_limited(client):
    limit = client.app_ctx.settings.rate_limit_predict_per_minute
    codes = [predict(client).status_code for _ in range(limit + 1)]
    assert codes[:limit] == [200] * limit
    assert codes[-1] == 429
    r = predict(client)
    assert r.headers["Retry-After"].isdigit()
    assert r.json()["error"]["code"] == "RATE_LIMITED"
