"""IMD gridded daily maximum temperature (1 x 1 degree, one binary .GRD file per year).

IMD has no REST API for this. The files are served by a form POST on the IMD Pune
site, and that host is not always reachable (its TLS handshake failed from the
setup machine on 2026-09-28). The adapter therefore has two paths:

- ``http``: POST the year to ``IMD_GRIDDED_TMAX_URL``, as the IMD download page does.
- ``inbox``: read a file you downloaded by hand into ``IMD_INBOX_DIR``, keeping
  IMD's own name (``Maxtemp_MaxT_<year>.GRD``).

``auto`` (the default) checks the inbox first and falls back to HTTP.

File format (IMD documentation): little-endian float32, days x 31 lat x 31 lon,
lat 7.5-37.5 N and lon 67.5-97.5 E in 1 deg steps, 99.9 = no data (sea/outside India).
"""

import math
from datetime import date

import numpy as np
import pandas as pd

from heatwave_ml.ingestion.adapters.base import Chunk, FetchResult, NativePayload
from heatwave_ml.ingestion.http import HttpClient, SourceRequestError, SourceUnavailable
from heatwave_ml.ingestion.regions import Region

GRID_LATS = np.arange(7.5, 37.6, 1.0)
GRID_LONS = np.arange(67.5, 97.6, 1.0)
MISSING_VALUE = 99.9

MANUAL_DOWNLOAD_HELP = (
    "Download it by hand from https://www.imdpune.gov.in/cmpg/Griddata/Max_1_Bin.html "
    "(select the year), save it as {inbox}/Maxtemp_MaxT_{year}.GRD and re-run."
)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def parse_grid(content: bytes, year: int) -> np.ndarray:
    """Return a (days, lat, lon) float array with missing cells as NaN."""
    days = 366 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 365
    expected = days * len(GRID_LATS) * len(GRID_LONS) * 4
    if len(content) != expected:
        raise SourceRequestError(
            f"IMD {year} file is {len(content)} bytes, expected {expected} "
            f"({days} days x 31 x 31 float32). Starts with {content[:80]!r}"
        )
    grid = np.frombuffer(content, dtype="<f4").reshape(days, len(GRID_LATS), len(GRID_LONS))
    return np.where(np.isclose(grid, MISSING_VALUE), np.nan, grid.astype("float64"))


def nearest_valid_cell(grid: np.ndarray, region: Region) -> tuple[int, int, float]:
    """Nearest grid cell that has data. Coastal points often fall in an all-sea cell."""
    has_data = ~np.isnan(grid).all(axis=0)
    best = None
    for i, j in zip(*np.nonzero(has_data), strict=True):
        distance = _distance_km(region.lat, region.lon, GRID_LATS[i], GRID_LONS[j])
        if best is None or distance < best[2]:
            best = (int(i), int(j), distance)
    if best is None:
        raise SourceRequestError("IMD grid contains no valid cells")
    return best


class ImdGriddedTmaxAdapter:
    name = "imd"
    key_columns = ("region_id", "date")
    continuous_dates = True

    def __init__(
        self,
        http: HttpClient,
        url: str,
        inbox_dir,
        regions: list[Region],
        mode: str = "auto",
    ):
        self.http = http
        self.url = url
        self.inbox_dir = inbox_dir
        self.regions = regions
        self.mode = mode

    @staticmethod
    def year_chunks(start_year: int, end_year: int, today: date) -> list[Chunk]:
        """One chunk per year. The file covers every region, so chunks are not per region."""
        return [
            Chunk(
                key=f"year={year}",
                start=date(year, 1, 1),
                end=date(year, 12, 31),
                resumable=year < today.year,
            )
            for year in range(start_year, end_year + 1)
        ]

    def _inbox_file(self, year: int):
        matches = sorted(
            p
            for p in self.inbox_dir.glob("*")
            if p.suffix.lower() == ".grd" and str(year) in p.stem
        )
        return matches[0] if matches else None

    def _download(self, year: int) -> tuple[bytes, str]:
        inbox_file = self._inbox_file(year) if self.mode in {"auto", "inbox"} else None
        if inbox_file is not None:
            return inbox_file.read_bytes(), f"inbox:{inbox_file.name}"
        if self.mode == "inbox":
            raise SourceUnavailable(
                f"No IMD {year} file in {self.inbox_dir}. "
                + MANUAL_DOWNLOAD_HELP.format(inbox=self.inbox_dir, year=year)
            )
        try:
            response = self.http.request("POST", self.url, data={"maxtemp": str(year)})
        except SourceUnavailable as exc:
            raise SourceUnavailable(
                f"{exc}. " + MANUAL_DOWNLOAD_HELP.format(inbox=self.inbox_dir, year=year)
            ) from exc
        return response.content, "http"

    def fetch(self, chunk: Chunk) -> FetchResult:
        year = chunk.start.year
        content, origin = self._download(year)
        if not content:
            return FetchResult(frame=pd.DataFrame(), notes={"origin": origin})

        grid = parse_grid(content, year)
        dates = pd.date_range(chunk.start, chunk.end, freq="D")
        frames, cells = [], {}
        for region in self.regions:
            i, j, distance = nearest_valid_cell(grid, region)
            cells[region.id] = {
                "grid_lat": float(GRID_LATS[i]),
                "grid_lon": float(GRID_LONS[j]),
                "distance_km": round(distance, 1),
            }
            frames.append(
                pd.DataFrame(
                    {
                        "region_id": region.id,
                        "date": dates,
                        "tmax_c": grid[:, i, j],
                        "grid_lat": GRID_LATS[i],
                        "grid_lon": GRID_LONS[j],
                        "grid_distance_km": round(distance, 1),
                    }
                )
            )

        return FetchResult(
            frame=pd.concat(frames, ignore_index=True),
            native=NativePayload(content, "grd"),
            notes={"origin": origin, "cells": cells},
        )
