"""Backend configuration, loaded from environment variables (see backend/.env.example).

Relative paths in these settings are resolved against the repository root, so the
service behaves the same regardless of the directory it is launched from.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "staging", "production", "test"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Part 08. Relative sqlite paths resolve from the repo root; sqlite:///:memory: for tests.
    database_url: str = "sqlite:///data/local/heatwave.db"
    database_backup_dir: Path = Path("data/local/backups")

    model_artifact_dir: Path = Path("ml/artifacts")
    model_registry_dir: Path = Path("ml/registry")
    # "production" follows ml/registry/production.json (Part 05). Never "whatever is
    # newest": promotion is an explicit, recorded action. An exact version id pins one.
    model_version: str = "production"
    risk_config_path: Path = Path("config/risk_classes.yaml")
    seasonal_normals_file: Path = Path("config/seasonal_normals.csv")
    monitored_regions_file: Path = Path("config/regions.yaml")
    alert_channels_file: Path = Path("config/alert_channels.yaml")
    recommended_actions_file: Path = Path("config/recommended_actions.yaml")

    # Live inference reads the conditions the pipeline already ingested (Part 07 §2
    # decision, docs/api/README.md): the backend makes no calls to weather providers.
    weather_features_file: Path = Path("data/sample/forecast_features.csv")
    weather_stale_after_hours: int = 36  # older data is still served, but flagged stale

    rate_limit_predict_per_minute: int = 30
    rate_limit_alerts_per_minute: int = 20
    rate_limit_login_per_minute: int = 10

    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    auth_secret_key: SecretStr = SecretStr("change-me-local-only")
    auth_token_ttl_minutes: int = 60
    # Local/test only: one seeded demo official, until Part 15 adds real users (Part 08).
    demo_user_username: str = "official"
    demo_user_password: SecretStr = SecretStr("demo-official-local")

    # Part 09, docs/notifications/README.md. mock = nothing leaves the process.
    notifications_mode: Literal["mock", "live"] = "mock"
    # background = POST/PATCH returns with channels PENDING, a worker thread delivers and
    # the UI polls GET /alerts/{id}; inline = deliver before responding (tests, debugging).
    notifications_dispatch: Literal["background", "inline"] = "background"
    notification_templates_file: Path = Path("config/notification_templates.yaml")
    notification_recipients_file: Path = Path("config/notification_recipients.yaml")
    notification_max_attempts: int = Field(3, ge=1, le=10)  # transient failures only
    notification_backoff_seconds: float = Field(2.0, ge=0)  # doubles each retry
    notification_timeout_seconds: float = Field(10.0, gt=0)  # per provider call
    email_provider: Literal["", "sendgrid"] = ""
    email_api_key: SecretStr = SecretStr("")
    email_from_address: str = ""
    sms_provider: Literal["", "twilio"] = ""
    sms_account_sid: str = ""
    sms_api_key: SecretStr = SecretStr("")  # Twilio auth token
    sms_sender_id: str = ""  # Twilio "From" number

    nasa_power_base_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point"

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator(
        "model_artifact_dir",
        "model_registry_dir",
        "risk_config_path",
        "seasonal_normals_file",
        "monitored_regions_file",
        "alert_channels_file",
        "recommended_actions_file",
        "weather_features_file",
        "database_backup_dir",
        "notification_templates_file",
        "notification_recipients_file",
    )
    @classmethod
    def _resolve_from_repo_root(cls, value: Path) -> Path:
        return value if value.is_absolute() else REPO_ROOT / value


@lru_cache
def get_settings() -> Settings:
    return Settings()
