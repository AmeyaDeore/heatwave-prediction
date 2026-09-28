"""Open-Meteo forecast API: the next 1-3 days of weather, for live inference only.

Chosen as the forecast feed because NASA POWER has no forecast product and IMD
publishes no machine-readable district forecast. It is public and keyless, and
returns the same five fields we take from NASA POWER. Historical training data
never comes from here. See docs/decisions/0002-data-sources.md.
"""

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from heatwave_ml.ingestion.adapters.base import Chunk, FetchResult, NativePayload
from heatwave_ml.ingestion.http import HttpClient, SourceRequestError
from heatwave_ml.ingestion.regions import Region

DAILY_VARIABLES = {
    "temperature_2m_max": "tmax_c",
    "relative_humidity_2m_mean": "rh_pct",
    "wind_speed_10m_mean": "wind_ms",
    "shortwave_radiation_sum": "solar_mj_m2",
    "precipitation_sum": "precip_mm",
}

TIMEZONE = "Asia/Kolkata"


class OpenMeteoForecastAdapter:
    name = "open_meteo_forecast"
    key_columns = ("region_id", "date")
    continuous_dates = True

    def __init__(self, http: HttpClient, base_url: str):
        self.http = http
        self.base_url = base_url

    @staticmethod
    def forecast_chunks(regions: list[Region], today: date, days: int) -> list[Chunk]:
        """Today plus the next ``days`` days. Never skipped: every run is a fresh forecast."""
        return [
            Chunk(
                key=f"region={region.id}/issued={today.isoformat()}",
                start=today,
                end=today + timedelta(days=days),
                region=region,
                resumable=False,
            )
            for region in regions
        ]

    def fetch(self, chunk: Chunk) -> FetchResult:
        region = chunk.region
        issued_at = datetime.now(UTC)
        response = self.http.request(
            "GET",
            self.base_url,
            params={
                "latitude": region.lat,
                "longitude": region.lon,
                "daily": ",".join(DAILY_VARIABLES),
                "wind_speed_unit": "ms",
                "timezone": TIMEZONE,
                "start_date": chunk.start.isoformat(),
                "end_date": chunk.end.isoformat(),
            },
        )
        try:
            payload = response.json()
            daily = payload["daily"]
            frame = pd.DataFrame(
                {"date": pd.to_datetime(daily["time"])}
                | {column: daily[name] for name, column in DAILY_VARIABLES.items()}
            )
        except (ValueError, KeyError) as exc:
            raise SourceRequestError(f"Unexpected Open-Meteo response shape: {exc!r}") from exc

        if not frame.empty:
            frame.insert(0, "region_id", region.id)
            frame["lead_days"] = (frame["date"] - pd.Timestamp(chunk.start)).dt.days
            frame["issued_at"] = issued_at.isoformat()
            frame["wind_height_m"] = 10
            frame["grid_lat"] = payload.get("latitude")
            frame["grid_lon"] = payload.get("longitude")

        return FetchResult(
            frame=frame,
            native=NativePayload(response.content, "json"),
            notes={"units": payload.get("daily_units", {})},
        )
