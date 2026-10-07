"""Where live inference gets its conditions (Part 07 §2 decision).

Decision: the backend **reads conditions the pipeline already ingested** rather than
calling Open-Meteo/NASA POWER itself. One code path fetches and unit-normalises weather
(Part 02/03), the API stays fast and offline-testable, and an outage shows up as stale
data instead of a failed request. The file is `heatwave-prepare sample`'s output.
"""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from heatwave_api.errors import UpstreamUnavailable

MAX_LEAD_DAYS = 3


@dataclass(frozen=True)
class WeatherReading:
    """Raw conditions for one region-day, in canonical units (°C, %, m/s at 2 m, MJ/m², mm)."""

    region_id: str
    date: date
    lead_days: int
    issued_at: datetime
    tmax_c: float | None
    rh_pct: float | None
    wind_ms: float | None
    solar_mj_m2: float | None
    precip_mm: float | None
    wind_height_m: float = 2.0
    source: str = "pipeline_forecast"

    def age_hours(self, now: datetime | None = None) -> float:
        return ((now or datetime.now(UTC)) - self.issued_at).total_seconds() / 3600


class WeatherSource(Protocol):
    def reading(self, region_id: str, lead_days: int = 0) -> WeatherReading: ...

    def forecast(self, region_id: str) -> list[WeatherReading]: ...

    def current(self) -> list[WeatherReading]:
        """Today's reading for every region that has one."""
        ...


def _number(value) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


class PipelineWeatherSource:
    """Reads the pipeline's forecast-features CSV, re-reading it when the file changes."""

    REQUIRED = ("region_id", "date", "lead_days", "issued_at", "tmax_c")

    def __init__(self, path: Path):
        self.path = Path(path)
        self._mtime: float | None = None
        self._readings: dict[tuple[str, int], WeatherReading] = {}

    def _load(self) -> dict[tuple[str, int], WeatherReading]:
        try:
            mtime = self.path.stat().st_mtime
        except OSError as exc:
            raise UpstreamUnavailable(
                "Current weather data is not available. The data pipeline has not produced it yet."
            ) from exc
        if mtime == self._mtime:
            return self._readings
        try:
            frame = pd.read_csv(self.path)
            missing = [c for c in self.REQUIRED if c not in frame.columns]
            if missing:
                raise ValueError(f"missing columns {missing}")
            readings = {}
            for row in frame.to_dict("records"):
                lead = int(row["lead_days"])
                readings[(row["region_id"], lead)] = WeatherReading(
                    region_id=row["region_id"],
                    date=date.fromisoformat(str(row["date"])[:10]),
                    lead_days=lead,
                    issued_at=datetime.fromisoformat(str(row["issued_at"])).astimezone(UTC),
                    tmax_c=_number(row["tmax_c"]),
                    rh_pct=_number(row.get("rh_pct")),
                    wind_ms=_number(row.get("wind_ms")),
                    solar_mj_m2=_number(row.get("solar_mj_m2")),
                    precip_mm=_number(row.get("precip_mm")),
                    wind_height_m=_number(row.get("wind_height_m")) or 2.0,
                )
        except (ValueError, KeyError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise UpstreamUnavailable(
                "Current weather data could not be read. The pipeline output is malformed."
            ) from exc
        self._mtime, self._readings = mtime, readings
        return readings

    def reading(self, region_id: str, lead_days: int = 0) -> WeatherReading:
        found = self._load().get((region_id, lead_days))
        if found is None:
            raise UpstreamUnavailable(
                f"No weather data for region '{region_id}' at lead {lead_days} day(s)."
            )
        return found

    def forecast(self, region_id: str) -> list[WeatherReading]:
        rows = sorted(
            (r for (rid, _), r in self._load().items() if rid == region_id),
            key=lambda r: r.lead_days,
        )
        if not rows:
            raise UpstreamUnavailable(f"No weather data for region '{region_id}'.")
        return rows

    def current(self) -> list[WeatherReading]:
        return sorted(
            (r for (_, lead), r in self._load().items() if lead == 0), key=lambda r: r.region_id
        )
