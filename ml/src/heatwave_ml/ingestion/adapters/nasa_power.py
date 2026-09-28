"""NASA POWER daily point API: humidity, wind, solar radiation, precipitation (and Tmax).

Public, keyless API. Values come from MERRA-2 / CERES grids (~0.5 deg), so nearby
regions can map to the same grid cell. See docs/data/field-availability.md.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from heatwave_ml.ingestion.adapters.base import Chunk, FetchResult, NativePayload
from heatwave_ml.ingestion.http import HttpClient, SourceRequestError
from heatwave_ml.ingestion.regions import Region

# POWER parameter -> canonical column. community=AG reports solar radiation in MJ/m^2/day.
PARAMETERS = {
    "T2M_MAX": "tmax_c",
    "RH2M": "rh_pct",
    "WS2M": "wind_ms",
    "ALLSKY_SFC_SW_DWN": "solar_mj_m2",
    "PRECTOTCORR": "precip_mm",
}

# POWER back-fills recent days as late inputs arrive, so a chunk is only final
# (and safe to skip on resume) once its last day is older than this.
SETTLE_DAYS = 30


class NasaPowerAdapter:
    name = "nasa_power"
    key_columns = ("region_id", "date")
    continuous_dates = True

    def __init__(self, http: HttpClient, base_url: str):
        self.http = http
        self.base_url = base_url

    @staticmethod
    def historical_chunks(
        regions: list[Region], start: date, end: date, today: date
    ) -> list[Chunk]:
        """Whole calendar years per region, so a chunk key always means the same data."""
        last_day = min(end, today - timedelta(days=1))
        chunks = []
        for region in regions:
            for year in range(start.year, last_day.year + 1):
                chunk_end = min(date(year, 12, 31), last_day)
                chunks.append(
                    Chunk(
                        key=f"region={region.id}/year={year}",
                        start=date(year, 1, 1),
                        end=chunk_end,
                        region=region,
                        resumable=date(year, 12, 31) < today - timedelta(days=SETTLE_DAYS),
                    )
                )
        return chunks

    @staticmethod
    def recent_chunks(regions: list[Region], days: int, today: date) -> list[Chunk]:
        """The rolling window of recent observations that live inference uses as context."""
        return [
            Chunk(
                key=f"region={region.id}/recent={today.isoformat()}",
                start=today - timedelta(days=days),
                end=today - timedelta(days=1),
                region=region,
                resumable=False,
            )
            for region in regions
        ]

    def fetch(self, chunk: Chunk) -> FetchResult:
        region = chunk.region
        response = self.http.request(
            "GET",
            self.base_url,
            params={
                "parameters": ",".join(PARAMETERS),
                "community": "AG",
                "latitude": region.lat,
                "longitude": region.lon,
                "start": chunk.start.strftime("%Y%m%d"),
                "end": chunk.end.strftime("%Y%m%d"),
                "time-standard": "LST",
                "format": "JSON",
            },
        )
        try:
            payload = response.json()
            values = payload["properties"]["parameter"]
            fill_value = payload["header"]["fill_value"]
            units = {name: payload["parameters"][name]["units"] for name in PARAMETERS}
        except (ValueError, KeyError) as exc:
            raise SourceRequestError(f"Unexpected NASA POWER response shape: {exc!r}") from exc

        frame = pd.DataFrame({column: values.get(name, {}) for name, column in PARAMETERS.items()})
        if not frame.empty:
            # Decode POWER's documented "missing" sentinel. Nothing else is changed.
            frame = frame.replace(fill_value, np.nan)
            frame.index = pd.to_datetime(frame.index, format="%Y%m%d")
            frame = frame.rename_axis("date").reset_index()
            frame.insert(0, "region_id", region.id)
            frame["wind_height_m"] = 2

        return FetchResult(
            frame=frame,
            native=NativePayload(response.content, "json"),
            notes={"units": units, "upstream_sources": payload["header"].get("sources", [])},
        )
