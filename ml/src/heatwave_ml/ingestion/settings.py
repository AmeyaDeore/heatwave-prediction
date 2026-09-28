"""Ingestion settings, loaded from environment variables (see ml/.env.example).

Relative paths resolve against the repository root, so the CLI behaves the same
from any working directory.
"""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ML_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = ML_DIR.parent


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class IngestionSettings:
    raw_data_dir: Path
    regions_file: Path
    random_seed: int

    nasa_power_base_url: str
    open_meteo_forecast_url: str
    imd_tmax_url: str
    imd_fetch_mode: str  # auto | inbox | http
    imd_inbox_dir: Path

    training_start: date
    training_end: date
    imd_history_start_year: int
    nasa_power_recent_days: int
    forecast_days: int
    synthetic_record_count: int

    http_timeout_seconds: float
    max_attempts: int
    backoff_base_seconds: float

    @classmethod
    def from_env(cls, env_file: Path | None = ML_DIR / ".env") -> "IngestionSettings":
        if env_file is not None:
            load_dotenv(env_file, override=False)
        env = os.environ.get

        imd_fetch_mode = env("IMD_FETCH_MODE", "auto")
        if imd_fetch_mode not in {"auto", "inbox", "http"}:
            raise ValueError(f"IMD_FETCH_MODE must be auto, inbox or http, got {imd_fetch_mode!r}")

        return cls(
            raw_data_dir=_path(env("RAW_DATA_DIR", "data/raw")),
            regions_file=_path(env("MONITORED_REGIONS_FILE", "config/regions.yaml")),
            random_seed=int(env("RANDOM_SEED", "42")),
            nasa_power_base_url=env(
                "NASA_POWER_BASE_URL", "https://power.larc.nasa.gov/api/temporal/daily/point"
            ),
            open_meteo_forecast_url=env(
                "OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast"
            ),
            imd_tmax_url=env(
                "IMD_GRIDDED_TMAX_URL", "https://www.imdpune.gov.in/cmpg/Griddata/maxtemp.php"
            ),
            imd_fetch_mode=imd_fetch_mode,
            imd_inbox_dir=_path(env("IMD_INBOX_DIR", "data/raw/imd/_inbox")),
            training_start=date.fromisoformat(env("TRAINING_START_DATE", "2000-01-01")),
            training_end=date.fromisoformat(env("TRAINING_END_DATE", "2024-12-31")),
            imd_history_start_year=int(env("IMD_HISTORY_START_YEAR", "1991")),
            nasa_power_recent_days=int(env("NASA_POWER_RECENT_DAYS", "14")),
            forecast_days=int(env("FORECAST_DAYS", "3")),
            synthetic_record_count=int(env("SYNTHETIC_RECORD_COUNT", "5000")),
            http_timeout_seconds=float(env("INGEST_HTTP_TIMEOUT_SECONDS", "60")),
            max_attempts=int(env("INGEST_MAX_ATTEMPTS", "4")),
            backoff_base_seconds=float(env("INGEST_BACKOFF_BASE_SECONDS", "2")),
        )
