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

    database_url: str = "sqlite:///data/local/heatwave.db"

    model_artifact_dir: Path = Path("ml/artifacts")
    model_registry_dir: Path = Path("ml/registry")
    # "production" follows ml/registry/production.json (Part 05). Never "whatever is
    # newest": promotion is an explicit, recorded action. An exact version id pins one.
    model_version: str = "production"
    risk_config_path: Path = Path("config/risk_classes.yaml")

    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    auth_secret_key: SecretStr = SecretStr("change-me-local-only")
    auth_token_ttl_minutes: int = 60

    notifications_mode: Literal["mock", "live"] = "mock"
    email_provider: str = ""
    email_api_key: SecretStr = SecretStr("")
    email_from_address: str = ""
    sms_provider: str = ""
    sms_api_key: SecretStr = SecretStr("")
    sms_sender_id: str = ""

    nasa_power_base_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point"

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("model_artifact_dir", "model_registry_dir", "risk_config_path")
    @classmethod
    def _resolve_from_repo_root(cls, value: Path) -> Path:
        return value if value.is_absolute() else REPO_ROOT / value


@lru_cache
def get_settings() -> Settings:
    return Settings()
