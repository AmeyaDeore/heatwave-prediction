from datetime import date

import numpy as np
import pytest
from conftest import make_response

from heatwave_ml.ingestion.adapters.imd import GRID_LATS, GRID_LONS, ImdGriddedTmaxAdapter
from heatwave_ml.ingestion.adapters.nasa_power import NasaPowerAdapter
from heatwave_ml.ingestion.adapters.open_meteo import OpenMeteoForecastAdapter
from heatwave_ml.ingestion.adapters.synthetic import SyntheticAdapter
from heatwave_ml.ingestion.http import SourceRequestError, SourceUnavailable
from heatwave_ml.ingestion.regions import load_regions
from heatwave_ml.ingestion.settings import REPO_ROOT


def test_region_config_is_loaded_not_hardcoded():
    regions = load_regions(REPO_ROOT / "config" / "regions.yaml")

    assert {r.id for r in regions} >= {"mumbai", "kurla", "andheri", "dharavi", "colaba"}
    with pytest.raises(ValueError, match="Unknown region"):
        load_regions(REPO_ROOT / "config" / "regions.yaml", ["atlantis"])


# --- NASA POWER ---------------------------------------------------------------

POWER_PAYLOAD = {
    "properties": {
        "parameter": {
            "T2M_MAX": {"20240501": 40.28, "20240502": -999.0},
            "RH2M": {"20240501": 48.07, "20240502": 49.75},
            "WS2M": {"20240501": 2.42, "20240502": 2.04},
            "ALLSKY_SFC_SW_DWN": {"20240501": 28.12, "20240502": 28.5},
            "PRECTOTCORR": {"20240501": 0.0, "20240502": 0.0},
        }
    },
    "header": {"fill_value": -999.0, "sources": ["MERRA2"]},
    "parameters": {
        p: {"units": "x"} for p in ("T2M_MAX", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN", "PRECTOTCORR")
    },
}


def test_nasa_power_flattens_to_canonical_columns_and_decodes_fill_value(fake_http, regions):
    client, session = fake_http(make_response(200, POWER_PAYLOAD))
    adapter = NasaPowerAdapter(client, "https://power")
    chunk = adapter.historical_chunks(
        regions[:1], date(2024, 5, 1), date(2024, 5, 2), date(2026, 1, 1)
    )[0]

    result = adapter.fetch(chunk)

    frame = result.frame
    assert list(frame.columns[:2]) == ["region_id", "date"]
    assert {"tmax_c", "rh_pct", "wind_ms", "solar_mj_m2", "precip_mm"} <= set(frame.columns)
    assert frame.loc[0, "tmax_c"] == 40.28
    assert np.isnan(frame.loc[1, "tmax_c"])  # -999 sentinel decoded, row kept
    assert result.native.extension == "json"
    assert session.calls[0][2]["params"]["start"] == "20240101"  # whole-year chunk


def test_nasa_power_chunks_are_whole_years_and_recent_years_are_not_resumable(regions):
    chunks = NasaPowerAdapter.historical_chunks(
        regions[:1], date(2023, 6, 1), date(2030, 1, 1), today=date(2024, 3, 10)
    )

    assert [c.key for c in chunks] == ["region=mumbai/year=2023", "region=mumbai/year=2024"]
    assert chunks[0].resumable and not chunks[1].resumable
    assert chunks[1].end == date(2024, 3, 9)  # never asks for the future


def test_nasa_power_unexpected_shape_is_a_request_error(fake_http, regions):
    client, _ = fake_http(make_response(200, {"messages": ["oops"]}))
    chunk = NasaPowerAdapter.recent_chunks(regions[:1], 7, date(2026, 9, 28))[0]

    with pytest.raises(SourceRequestError):
        NasaPowerAdapter(client, "https://power").fetch(chunk)


# --- Open-Meteo forecast ------------------------------------------------------

FORECAST_PAYLOAD = {
    "latitude": 19.0,
    "longitude": 72.9,
    "daily_units": {"temperature_2m_max": "°C"},
    "daily": {
        "time": ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"],
        "temperature_2m_max": [31.0, 31.6, 32.0, 32.0],
        "relative_humidity_2m_mean": [79, 79, 81, 78],
        "wind_speed_10m_mean": [1.5, 1.8, 1.6, 1.5],
        "shortwave_radiation_sum": [20.4, 19.6, 20.7, 20.6],
        "precipitation_sum": [2.7, 0.8, 4.5, None],
    },
}


def test_forecast_has_lead_days_and_is_never_skipped(fake_http, regions):
    client, session = fake_http(make_response(200, FORECAST_PAYLOAD))
    adapter = OpenMeteoForecastAdapter(client, "https://om")
    chunk = adapter.forecast_chunks(regions[:1], date(2026, 9, 28), days=3)[0]

    frame = adapter.fetch(chunk).frame

    assert not chunk.resumable
    assert frame["lead_days"].tolist() == [0, 1, 2, 3]
    assert frame["wind_height_m"].iloc[0] == 10
    assert session.calls[0][2]["params"]["end_date"] == "2026-10-01"


# --- IMD gridded Tmax ---------------------------------------------------------


def imd_year_bytes(year_days: int, value_at: dict) -> bytes:
    """A synthetic IMD-format file: all cells 99.9 (missing) except those in value_at."""
    grid = np.full((year_days, 31, 31), 99.9, dtype="<f4")
    for (lat, lon), value in value_at.items():
        grid[:, list(GRID_LATS).index(lat), list(GRID_LONS).index(lon)] = value
    return grid.tobytes()


def test_imd_reads_inbox_file_and_picks_nearest_cell_with_data(tmp_path, fake_http, regions):
    # 18.5/72.5 is the nearest cell to Mumbai but is sea (missing); 19.5/73.5 has data.
    (tmp_path / "Maxtemp_MaxT_2023.GRD").write_bytes(imd_year_bytes(365, {(19.5, 73.5): 34.5}))
    client, session = fake_http()
    adapter = ImdGriddedTmaxAdapter(client, "https://imd", tmp_path, regions, mode="auto")

    result = adapter.fetch(adapter.year_chunks(2023, 2023, date(2026, 1, 1))[0])

    frame = result.frame
    assert len(frame) == 365 * len(regions)
    assert frame["tmax_c"].round(1).eq(34.5).all()
    assert (frame["grid_lat"].iloc[0], frame["grid_lon"].iloc[0]) == (19.5, 73.5)
    assert result.notes["origin"] == "inbox:Maxtemp_MaxT_2023.GRD"
    assert session.calls == []  # inbox wins, no network


def test_imd_decodes_missing_days_to_nan(tmp_path, fake_http, regions):
    content = bytearray(imd_year_bytes(366, {(18.5, 72.5): 33.0}))  # 2024 is a leap year
    grid = np.frombuffer(bytes(content), dtype="<f4").reshape(366, 31, 31).copy()
    grid[10, list(GRID_LATS).index(18.5), list(GRID_LONS).index(72.5)] = 99.9
    (tmp_path / "Maxtemp_MaxT_2024.GRD").write_bytes(grid.tobytes())
    client, _ = fake_http()

    frame = (
        ImdGriddedTmaxAdapter(client, "u", tmp_path, regions[:1])
        .fetch(ImdGriddedTmaxAdapter.year_chunks(2024, 2024, date(2026, 1, 1))[0])
        .frame
    )

    assert frame["tmax_c"].isna().sum() == 1


def test_imd_wrong_size_file_is_a_request_error(fake_http, regions, tmp_path):
    client, _ = fake_http(make_response(200, b"<html>Service unavailable</html>"))
    adapter = ImdGriddedTmaxAdapter(client, "https://imd", tmp_path, regions, mode="http")

    with pytest.raises(SourceRequestError, match="expected"):
        adapter.fetch(adapter.year_chunks(2023, 2023, date(2026, 1, 1))[0])


def test_imd_unreachable_explains_manual_fallback(fake_http, regions, tmp_path):
    import requests

    client, _ = fake_http(*[requests.ConnectionError("TLS EOF")] * 3)
    adapter = ImdGriddedTmaxAdapter(client, "https://imd", tmp_path, regions, mode="auto")

    with pytest.raises(SourceUnavailable, match="Download it by hand"):
        adapter.fetch(adapter.year_chunks(2023, 2023, date(2026, 1, 1))[0])


# --- Synthetic ----------------------------------------------------------------


def test_synthetic_is_deterministic_for_a_seed(regions):
    def build(seed):
        adapter = SyntheticAdapter(regions, 500, seed, date(2000, 1, 1), date(2024, 12, 31))
        return adapter.fetch(adapter.chunks()[0]).frame

    first, again, other = build(42), build(42), build(7)

    assert len(first) == 500
    assert first.equals(again)
    assert not first.equals(other)
    assert {"tmax_c", "normal_tmax_c", "rh_pct", "wind_ms", "solar_mj_m2", "precip_mm"} <= set(
        first
    )
