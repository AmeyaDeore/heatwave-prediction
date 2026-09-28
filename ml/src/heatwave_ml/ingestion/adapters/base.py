"""The contract every source adapter implements.

An adapter only talks to its source. It splits a request into ``Chunk`` units of
work, and ``fetch`` returns one chunk's data in two forms:

- ``native``: the source's bytes, untouched, kept for audit and re-parsing.
- ``frame``: the same values flattened to one row per (region_id, date), with
  columns renamed to the canonical names below and the source's documented
  "missing" sentinel (e.g. NASA POWER's -999) decoded to null. That is the only
  change made. Units stay as the source reports them, and no row is dropped,
  capped or imputed. Cleaning is Part 03's job.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import pandas as pd

from heatwave_ml.ingestion.regions import Region

# Canonical raw column names. A source only emits the fields it actually has.
CANONICAL_FIELDS = {
    "tmax_c": "Daily maximum temperature, degC",
    "normal_tmax_c": "Seasonal normal maximum temperature, degC (synthetic source only)",
    "rh_pct": "Relative humidity, % (daily mean)",
    "wind_ms": "Wind speed, m/s (height differs by source: see wind_height_m)",
    "solar_mj_m2": "Surface shortwave downward radiation, MJ/m^2/day",
    "precip_mm": "Precipitation, mm/day",
}


@dataclass(frozen=True)
class Chunk:
    """One unit of work, landed and logged on its own.

    ``key`` is a relative partition path (e.g. ``region=mumbai/year=2023``). It
    names the landing directory and is what resume checks against.
    ``resumable`` chunks are skipped when already landed. Chunks whose data can
    still change (the current year, forecasts, recent windows) are always fetched.
    """

    key: str
    start: date
    end: date
    region: Region | None = None
    resumable: bool = True


@dataclass
class NativePayload:
    content: bytes
    extension: str  # "json", "grd", ...


@dataclass
class FetchResult:
    frame: pd.DataFrame
    native: NativePayload | None = None
    notes: dict = field(default_factory=dict)


class SourceAdapter(Protocol):
    name: str

    def fetch(self, chunk: Chunk) -> FetchResult:
        """Fetch one chunk. Raise SourceUnavailable / SourceRequestError on failure.

        "No data for this query" is not a failure: return an empty frame.
        """
        ...
