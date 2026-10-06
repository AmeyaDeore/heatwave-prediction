"""Current and forecast weather for live inference (Part 07 §2, decided in ADR 0006).

The backend calls the same Open-Meteo forecast adapter Part 02 built, through Part
03's ``build_features``, and stores what it fetched in ``weather_snapshots``. A stored
forecast younger than WEATHER_CACHE_MINUTES is reused, so the dashboard polling
every region does not refetch on every request, and the cache lives in the database
rather than in the process (Part 07 §7: the service stays stateless).

Historical training data never comes through here; that stays Part 02's batch job.
"""

from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from heatwave_api.db.repository import FEATURE_FIELDS, Repository
from heatwave_api.errors import UpstreamBadResponse, UpstreamUnavailable
from heatwave_api.reference import MAX_FORECAST_DAYS
from heatwave_ml.features import SeasonalNormals, build_features
from heatwave_ml.ingestion.adapters.open_meteo import OpenMeteoForecastAdapter
from heatwave_ml.ingestion.http import (
    HttpClient,
    RetryPolicy,
    SourceRequestError,
    SourceUnavailable,
)
from heatwave_ml.ingestion.regions import Region

# The adapter requests daily values in this time zone, so "today" is India's today.
LOCAL_TZ = ZoneInfo("Asia/Kolkata")


class ForecastProvider(Protocol):
    name: str

    def forecast(self, region: Region, today: date, days: int) -> pd.DataFrame:
        """Today plus ``days`` days for one region: canonical raw columns, plus
        lead_days, issued_at and wind_height_m. Raises UpstreamUnavailable or
        UpstreamBadResponse."""
        ...


class OpenMeteoProvider:
    name = "open_meteo_forecast"

    def __init__(self, url: str, timeout_seconds: float, max_attempts: int):
        policy = RetryPolicy(
            max_attempts=max_attempts, backoff_base_seconds=0.5, backoff_max_seconds=2
        )
        self.adapter = OpenMeteoForecastAdapter(HttpClient(policy, timeout_seconds), url)

    def forecast(self, region: Region, today: date, days: int) -> pd.DataFrame:
        chunk = OpenMeteoForecastAdapter.forecast_chunks([region], today, days)[0]
        try:
            result = self.adapter.fetch(chunk)
        except SourceUnavailable as exc:
            raise UpstreamUnavailable(
                "The weather forecast service is not reachable right now. Try again shortly.",
                details={"source": self.name},
            ) from exc
        except SourceRequestError as exc:
            raise UpstreamBadResponse(
                "The weather forecast service returned an error.", details={"source": self.name}
            ) from exc
        return result.frame


class WeatherService:
    def __init__(
        self,
        provider: ForecastProvider,
        normals: SeasonalNormals,
        cache_minutes: int,
        clock=lambda: datetime.now(LOCAL_TZ),
    ):
        self.provider = provider
        self.normals = normals
        self.cache = timedelta(minutes=cache_minutes)
        self.clock = clock

    def now(self) -> datetime:
        return self.clock()

    def today(self) -> date:
        return self.now().astimezone(LOCAL_TZ).date()

    def forecast(self, repo: Repository, region: Region) -> list[dict]:
        """Today's forecast for ``region`` (lead 0..3) as stored snapshot rows, from
        the cache if fresh, else fetched and stored now."""
        now = self.now()
        today = self.today()
        if self.cache:
            since = (now - self.cache).astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
            cached = repo.latest_forecast(region.id, today.isoformat(), since)
            if cached and max(r["lead_days"] for r in cached) >= MAX_FORECAST_DAYS:
                return cached

        frame = self.provider.forecast(region, today, MAX_FORECAST_DAYS)
        if frame.empty:
            raise UpstreamBadResponse(
                f"The weather forecast service returned no data for {region.name}.",
                details={"source": self.provider.name},
            )
        try:
            features = build_features(frame, self.normals)
        except (KeyError, ValueError) as exc:
            raise UpstreamBadResponse(
                "The weather forecast could not be used.", details={"source": self.provider.name}
            ) from exc
        fetched_at = now.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
        rows = []
        for _, f in features.iterrows():
            rows.append(
                {
                    "region_id": region.id,
                    "date": f["date"].date().isoformat(),
                    "kind": "FORECAST",
                    "lead_days": int(f["lead_days"]),
                    "issued_at": _issued_local(f["issued_at"]),
                    "source": self.provider.name,
                    "fetched_at": fetched_at,
                }
                | {k: _num(f[k]) for k in FEATURE_FIELDS}
            )
        ids = repo.insert_snapshots(rows)
        return [r | {"id": i} for r, i in zip(rows, ids, strict=True)]


def _num(value) -> float | None:
    return None if pd.isna(value) else round(float(value), 2)


def _issued_local(value) -> str:
    """issued_at in local time, so its date part is the local issue date the cache keys on."""
    return pd.Timestamp(value).tz_convert(LOCAL_TZ).isoformat(timespec="seconds")
