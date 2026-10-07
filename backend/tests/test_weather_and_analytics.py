from datetime import date

import pytest

from heatwave_api.errors import UpstreamUnavailable
from heatwave_api.weather import PipelineWeatherSource

HEADER = (
    "region_id,date,lead_days,issued_at,month,tmax_c,normal_tmax_c,"
    "rh_pct,wind_ms,solar_mj_m2,precip_mm,temp_deviation_c\n"
)


def test_weather_lists_every_region_with_derived_fields(client):
    rows = client.get("/api/v1/weather").json()["data"]
    assert len(rows) == 5
    mumbai = next(r for r in rows if r["region"]["id"] == "mumbai")
    assert mumbai["tmax_c"] == 41.0
    assert mumbai["normal_tmax_c"] == 34.0
    assert mumbai["temp_deviation_c"] == 7.0
    assert mumbai["provenance"]["stale"] is False


def test_weather_for_one_region_and_lead(client):
    rows = client.get("/api/v1/weather", params={"region_id": "kurla", "lead_days": 2}).json()[
        "data"
    ]
    assert len(rows) == 1
    assert rows[0]["lead_days"] == 2
    assert rows[0]["tmax_c"] == 43.0


def test_weather_errors(client, weather):
    assert client.get("/api/v1/weather", params={"region_id": "atlantis"}).status_code == 404
    assert client.get("/api/v1/weather", params={"lead_days": 9}).status_code == 422
    weather.fail = True
    assert client.get("/api/v1/weather").status_code == 503


def test_analytics_model_performance_comes_from_the_promoted_model(client):
    perf = client.get("/api/v1/analytics").json()["data"]["model_performance"]
    assert perf["model_version"] == "fake-model-v1"
    assert (perf["f1_macro"], perf["precision_macro"], perf["recall_macro"]) == (0.82, 0.8, 0.85)
    assert perf["per_class"]["HEATWAVE"] == {"precision": 0.7, "recall": 0.8, "f1": 0.75}
    assert perf["mean_confidence"] == 0.95


def test_analytics_is_empty_but_well_formed_before_any_prediction(client):
    d = client.get("/api/v1/analytics").json()["data"]
    assert d["predictions_in_period"] == 0
    assert d["risk_distribution"] == {"NORMAL": 0, "HEATWAVE": 0, "SEVERE_HEATWAVE": 0}
    assert d["temperature_trend"] == d["events_per_month"] == []


def test_analytics_aggregates_stored_predictions(client, weather):
    from fakes import reading

    weather.rows[("kurla", 0)] = reading("kurla", 0, tmax=47.0)
    for region in ("mumbai", "kurla", "kurla"):  # the repeat must not double count
        client.post("/api/v1/predict", json={"region_id": region})
    d = client.get("/api/v1/analytics").json()["data"]
    assert d["predictions_in_period"] == 2
    assert d["risk_distribution"] == {"NORMAL": 0, "HEATWAVE": 1, "SEVERE_HEATWAVE": 1}
    month = date.today().strftime("%Y-%m")
    assert d["events_per_month"] == [{"month": month, "heatwave_events": 1, "severe_events": 1}]
    point = d["temperature_trend"][0]
    assert (point["avg_tmax_c"], point["max_tmax_c"], point["predictions"]) == (44.0, 47.0, 2)

    only = client.get("/api/v1/analytics", params={"region_id": "mumbai"}).json()["data"]
    assert only["predictions_in_period"] == 1


def test_analytics_validates_its_query(client):
    assert client.get("/api/v1/analytics", params={"days": 0}).status_code == 422
    assert client.get("/api/v1/analytics", params={"region_id": "atlantis"}).status_code == 404


# -- the real file-backed weather source ---------------------------------------------


def write(tmp_path, rows):
    path = tmp_path / "forecast.csv"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


GOOD = "mumbai,2026-09-29,0,2026-09-29T06:00:00+00:00,9,36.5,33.0,60,2.0,22.0,0.0,3.5\n"


def test_pipeline_source_reads_readings(tmp_path):
    source = PipelineWeatherSource(write(tmp_path, GOOD))
    r = source.reading("mumbai", 0)
    assert (r.tmax_c, r.rh_pct, r.date) == (36.5, 60.0, date(2026, 9, 29))
    assert r.issued_at.tzinfo is not None
    assert [x.region_id for x in source.current()] == ["mumbai"]


def test_pipeline_source_treats_blank_values_as_missing(tmp_path):
    row = "mumbai,2026-09-29,0,2026-09-29T06:00:00+00:00,9,36.5,33.0,,2.0,22.0,0.0,3.5\n"
    assert PipelineWeatherSource(write(tmp_path, row)).reading("mumbai").rh_pct is None


def test_pipeline_source_picks_up_a_refreshed_file(tmp_path):
    import os

    path = write(tmp_path, GOOD)
    source = PipelineWeatherSource(path)
    assert source.reading("mumbai").tmax_c == 36.5
    path.write_text(HEADER + GOOD.replace("36.5", "44.0"), encoding="utf-8")
    os.utime(path, (1, 2_000_000_000))  # guarantee a different mtime
    assert source.reading("mumbai").tmax_c == 44.0


@pytest.mark.parametrize(
    "content",
    ["", "region_id,date\nmumbai,2026-09-29\n", HEADER + "mumbai,bad,0,x,9,1,1,1,1,1,1,1\n"],
)
def test_pipeline_source_reports_malformed_files_as_upstream_errors(tmp_path, content):
    path = tmp_path / "forecast.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(UpstreamUnavailable):
        PipelineWeatherSource(path).reading("mumbai")


def test_pipeline_source_reports_a_missing_file_and_missing_region(tmp_path):
    with pytest.raises(UpstreamUnavailable, match="not available"):
        PipelineWeatherSource(tmp_path / "absent.csv").reading("mumbai")
    with pytest.raises(UpstreamUnavailable, match="kurla"):
        PipelineWeatherSource(write(tmp_path, GOOD)).reading("kurla")
    with pytest.raises(UpstreamUnavailable):
        PipelineWeatherSource(write(tmp_path, GOOD)).reading("mumbai", 3)
