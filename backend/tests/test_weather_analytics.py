"""GET /weather and GET /analytics."""

from datetime import timedelta

import pytest
from api_support import NOW, heat

from heatwave_api.db import utcnow
from heatwave_api.errors import UpstreamUnavailable

TODAY = NOW.date()


def test_current_weather_for_every_region_with_its_latest_prediction(client, fakes):
    fakes.forecast.tmax["mumbai"] = [36.5, 33.0, 33.0, 33.0]
    prediction = client.post("/api/v1/predict", json={"region_id": "mumbai"}).json()["data"]
    data = client.get("/api/v1/weather").json()["data"]
    assert [i["region"]["id"] for i in data["items"]] == [
        "mumbai",
        "kurla",
        "andheri",
        "dharavi",
        "colaba",
    ]
    mumbai = data["items"][0]
    current = mumbai["current"]
    assert current["date"] == TODAY.isoformat() and current["kind"] == "FORECAST"
    assert current["tmax_c"] == 36.5
    assert current["temp_deviation_c"] == pytest.approx(36.5 - current["normal_tmax_c"], abs=0.01)
    assert current["display"]["temp_deviation_c"].startswith("+")
    assert mumbai["latest_prediction"]["prediction_id"] == prediction["prediction_id"]
    assert mumbai["latest_prediction"]["forecast_window"]["label"] == "Next 3 days"
    assert data["items"][1]["latest_prediction"] is None
    assert all(i["error"] is None for i in data["items"])


def test_one_failing_region_does_not_blank_the_dashboard(client, fakes):
    fakes.forecast.fail_regions = {"kurla"}
    response = client.get("/api/v1/weather")
    assert response.status_code == 200
    body = response.json()
    by_id = {i["region"]["id"]: i for i in body["data"]["items"]}
    assert by_id["kurla"]["current"] is None
    assert by_id["kurla"]["error"]["code"] == "WEATHER_SOURCE_UNAVAILABLE"
    assert by_id["mumbai"]["current"] is not None
    assert body["meta"]["warnings"] == [
        "Kurla: The weather forecast service is not reachable right now."
    ]


def test_weather_errors_when_nothing_can_be_shown(client, fakes):
    fakes.forecast.error = UpstreamUnavailable("down")
    assert client.get("/api/v1/weather").status_code == 503
    assert client.get("/api/v1/weather?region_id=kurla").status_code == 503
    assert client.get("/api/v1/weather?region_id=atlantis").status_code == 404


def _predict_days(client, region, temps_by_offset):
    """One client-supplied run per day, as a stream of daily predictions would be."""
    for offset, tmax in temps_by_offset.items():
        response = client.post(
            "/api/v1/predict", json={"region_id": region, "conditions": [heat(offset, tmax)]}
        )
        assert response.status_code == 201, response.text


def test_risk_distribution_and_monthly_events_count_region_days_once(client):
    _predict_days(client, "mumbai", {0: 42.0, -1: 41.0, -2: 33.0, -40: 42.0})
    # A later prediction for the same day supersedes the earlier one.
    _predict_days(client, "mumbai", {-2: 39.5})
    _predict_days(client, "kurla", {0: 42.0})

    data = client.get("/api/v1/analytics?region_id=mumbai&period=week").json()["data"]
    assert data["period"] == {
        "name": "week",
        "start": (TODAY - timedelta(days=6)).isoformat(),
        "end": TODAY.isoformat(),
        "days": 7,
    }
    # Mumbai's early-May normal is 34.7 °C: 42.0 is severe (+7.3), 41.0 (+6.3) and the
    # re-predicted 39.5 (+4.8) are heatwave days. Without supersession, day -2 would
    # still count as the NORMAL of its first prediction.
    dist = {c["risk_class"]: c for c in data["risk_distribution"]["classes"]}
    assert data["risk_distribution"]["total_region_days"] == 3
    assert {k: v["region_days"] for k, v in dist.items()} == {
        "NORMAL": 0,
        "HEATWAVE": 2,
        "SEVERE_HEATWAVE": 1,
    }
    assert dist["HEATWAVE"]["pct"] == 66.7

    events = {m["month"]: m for m in data["heatwave_events"]}
    assert list(events) == ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
    assert events["2026-05"] == {
        "month": "2026-05",
        "heatwave_days": 2,
        "severe_heatwave_days": 1,
        "event_days": 3,
    }
    assert events["2026-03"]["severe_heatwave_days"] == 1  # 40 days before 10 May
    assert "most recent prediction" in data["event_rule"]

    everywhere = client.get("/api/v1/analytics?period=week").json()["data"]
    assert everywhere["region"] is None
    assert everywhere["risk_distribution"]["total_region_days"] == 4


def test_temperature_trend_prefers_observations_and_marks_the_threshold(client, repo):
    client.get("/api/v1/weather?region_id=mumbai")  # stores today's forecast (33 °C)
    now = utcnow()
    repo.insert_snapshots(
        [
            {
                "region_id": "mumbai",
                "date": TODAY.isoformat(),
                "kind": "ACTUAL",
                "source": "imd",
                "tmax_c": 41.0,
                "normal_tmax_c": 33.0,
                "temp_deviation_c": 8.0,
                "fetched_at": now,
            },
            {
                "region_id": "mumbai",
                "date": (TODAY - timedelta(days=1)).isoformat(),
                "kind": "ACTUAL",
                "source": "imd",
                "tmax_c": 34.0,
                "normal_tmax_c": 33.0,
                "temp_deviation_c": 1.0,
                "fetched_at": now,
            },
        ]
    )
    trend = client.get("/api/v1/analytics?region_id=mumbai").json()["data"]["temperature_trend"]
    assert [p["date"] for p in trend] == [
        (TODAY - timedelta(days=1)).isoformat(),
        TODAY.isoformat(),
    ]
    yesterday, today = trend
    assert today["kind"] == "ACTUAL" and today["tmax_c"] == 41.0  # observation wins
    # Mumbai is coastal: heatwave at max(37, normal + 4.5), severe at max(37, normal + 6.5).
    assert (today["heatwave_threshold_c"], today["severe_threshold_c"]) == (37.5, 39.5)
    assert today["above_heatwave_threshold"] is True
    assert yesterday["above_heatwave_threshold"] is False


def test_analytics_carries_the_deployed_models_performance(client):
    performance = client.get("/api/v1/analytics").json()["data"]["model_performance"]
    assert performance["model_version"] == "xgboost-test"
    assert performance["averaging"] == "macro"
    assert performance["f1"] == 0.88


@pytest.mark.parametrize(
    "query", ["period=year", "months=0", "months=25", "end_date=yesterday", "region_id=BAD!"]
)
def test_invalid_analytics_query(client, query):
    assert client.get(f"/api/v1/analytics?{query}").status_code == 422
