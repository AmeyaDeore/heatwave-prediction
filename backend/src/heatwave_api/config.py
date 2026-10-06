"""Backend configuration, loaded from environment variables (see backend/.env.example).

Relative paths in these settings are resolved against the repository root, so the
service behaves the same regardless of the directory it is launched from.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

DEFAULT_AUTH_SECRET = "change-me-local-only"  # pragma: allowlist secret
_RATE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour)\s*$")
_RATE_SECONDS = {"second": 1, "minute": 60, "hour": 3600}


def parse_rate(value: str) -> tuple[int, int]:
    """ "30/minute" -> (30, 60). "0/minute" disables the limit."""
    match = _RATE.match(value)
    if not match:
        raise ValueError(f"rate limit {value!r} must look like '30/minute' (second|minute|hour)")
    return int(match.group(1)), _RATE_SECONDS[match.group(2)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "staging", "production", "test"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: str = "sqlite:///data/local/heatwave.db"

    model_artifact_dir: Path = Path("ml/artifacts")
    model_registry_dir: Path = Path("ml/registry")
    # "production" follows ml/registry/production.json (Part 05). Never "whatever is
    # newest": promotion is an explicit, recorded action. An exact version id pins one.
    model_version: str = "production"
    risk_config_path: Path = Path("config/risk_classes.yaml")
    monitored_regions_file: Path = Path("config/regions.yaml")
    seasonal_normals_file: Path = Path("config/seasonal_normals.csv")
    recommended_actions_file: Path = Path("config/recommended_actions.yaml")

    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    # Per client address, per process (docs/api/README.md §Rate limiting).
    rate_limit_predict: str = "30/minute"
    rate_limit_alert_writes: str = "10/minute"
    rate_limit_login: str = "5/minute"

    auth_secret_key: SecretStr = SecretStr(DEFAULT_AUTH_SECRET)
    auth_token_ttl_minutes: int = Field(default=60, ge=5, le=24 * 60)
    # false: dashboard reads (GET endpoints and POST /predict) are open within the
    # deployed environment; alert writes always need a token (Part 15 §5).
    auth_required_for_reads: bool = False

    notifications_mode: Literal["mock", "live"] = "mock"
    # Mock mode only: channels whose delivery the mock reports as FAILED, so the
    # partial-failure path can be exercised end to end (e.g. EMERGENCY_SERVICES).
    notifications_mock_fail_channels: Annotated[list[str], NoDecode] = Field(default_factory=list)
    email_provider: str = ""
    email_api_key: SecretStr = SecretStr("")
    email_from_address: str = ""
    sms_provider: str = ""
    sms_api_key: SecretStr = SecretStr("")
    sms_sender_id: str = ""

    # Live inference reads the same Open-Meteo forecast adapter Part 02 built
    # (docs/decisions/0006-backend-api.md). Tighter retries than the batch pipeline:
    # a dashboard request should fail in seconds, not minutes.
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_http_timeout_seconds: float = Field(default=10.0, gt=0)
    weather_max_attempts: int = Field(default=2, ge=1, le=5)
    # A stored forecast younger than this is reused instead of re-fetched.
    weather_cache_minutes: int = Field(default=60, ge=0)

    nasa_power_base_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point"

    @field_validator("cors_allowed_origins", "notifications_mock_fail_channels", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("rate_limit_predict", "rate_limit_alert_writes", "rate_limit_login")
    @classmethod
    def _check_rate(cls, value: str) -> str:
        parse_rate(value)
        return value

    @field_validator(
        "model_artifact_dir",
        "model_registry_dir",
        "risk_config_path",
        "monitored_regions_file",
        "seasonal_normals_file",
        "recommended_actions_file",
    )
    @classmethod
    def _resolve_from_repo_root(cls, value: Path) -> Path:
        return value if value.is_absolute() else REPO_ROOT / value

    @property
    def runs_dir(self) -> Path:
        return self.model_artifact_dir / "runs"

    @property
    def sqlite_path(self) -> Path:
        """The SQLite file DATABASE_URL names (relative paths resolve from the repo root)."""
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError(
                f"DATABASE_URL {self.database_url.split(':', 1)[0]}:... is not supported yet: "
                "the service runs on SQLite (sqlite:///path). PostgreSQL is a later migration."
            )
        path = Path(self.database_url[len(prefix) :])
        return path if path.is_absolute() else REPO_ROOT / path

    def check_deployable(self) -> None:
        """Refuse settings that are only safe on a developer laptop."""
        if self.app_env in ("staging", "production"):
            secret = self.auth_secret_key.get_secret_value()
            if secret == DEFAULT_AUTH_SECRET or len(secret) < 32:
                raise ValueError(
                    "AUTH_SECRET_KEY must be set to a random value of at least 32 characters "
                    f"in {self.app_env}"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
