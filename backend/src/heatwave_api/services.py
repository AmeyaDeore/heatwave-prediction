"""Everything the service loads once at startup, in one container on ``app.state``.

``build_services`` is the production assembly. ``assemble_services`` takes the three
outside-world pieces (model, forecast provider, notifier) as arguments, so tests run
the real startup (migrations, region sync, model metadata) around fakes.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import get_args

from heatwave_api.actions import ActionPlan
from heatwave_api.config import Settings
from heatwave_api.db import Database, MigrationError
from heatwave_api.db.repository import Repository
from heatwave_api.inference import ModelService, Predictor, StartupError
from heatwave_api.notifications import MockNotifier, Notifier
from heatwave_api.ratelimit import RateLimiter
from heatwave_api.reference import ReferenceData, region_dict
from heatwave_api.schemas import Channel
from heatwave_api.security import TokenService
from heatwave_api.weather import ForecastProvider, OpenMeteoProvider, WeatherService

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    reference: ReferenceData
    actions: ActionPlan
    db: Database
    model: Predictor
    weather: WeatherService
    notifier: Notifier
    tokens: TokenService
    limiter: RateLimiter = field(default_factory=RateLimiter)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def assemble_services(
    settings: Settings,
    *,
    model: Predictor,
    provider: ForecastProvider,
    notifier: Notifier,
    weather_clock=None,
) -> Services:
    try:
        settings.check_deployable()
        reference = ReferenceData.load(settings.monitored_regions_file, settings.risk_config_path)
        actions = ActionPlan.load(settings.recommended_actions_file)
        db = Database(settings.sqlite_path)
        applied = db.migrate()
    except (ValueError, OSError, KeyError, MigrationError) as exc:
        raise StartupError(str(exc)) from exc
    if applied:
        log.info("database migrated", extra={"applied": applied, "database": str(db.path)})
    with db.connect() as conn:
        repo = Repository(conn)
        repo.sync_regions([region_dict(r) for r in reference.regions.values()])
        reference.known_regions = {r["id"]: r for r in repo.all_regions()}
        repo.activate_model(model.metadata() | {"deployed_at": _now()})
    weather_kwargs = {"clock": weather_clock} if weather_clock else {}
    weather = WeatherService(
        provider, model.normals, settings.weather_cache_minutes, **weather_kwargs
    )
    return Services(
        settings=settings,
        reference=reference,
        actions=actions,
        db=db,
        model=model,
        weather=weather,
        notifier=notifier,
        tokens=TokenService(
            settings.auth_secret_key.get_secret_value(), settings.auth_token_ttl_minutes
        ),
    )


def build_notifier(settings: Settings) -> Notifier:
    if settings.notifications_mode == "live":
        raise StartupError(
            "NOTIFICATIONS_MODE=live needs the Part 09 provider integrations, which do not "
            "exist yet. Use NOTIFICATIONS_MODE=mock."
        )
    unknown = set(settings.notifications_mock_fail_channels) - set(get_args(Channel))
    if unknown:
        raise StartupError(f"NOTIFICATIONS_MOCK_FAIL_CHANNELS has unknown channel(s) {unknown}")
    return MockNotifier(settings.notifications_mock_fail_channels)


def build_services(settings: Settings) -> Services:
    """The production startup. Raises StartupError instead of starting half-working."""
    reference = ReferenceData.load(settings.monitored_regions_file, settings.risk_config_path)
    notifier = build_notifier(settings)
    model = ModelService.load(settings, list(reference.regions))
    provider = OpenMeteoProvider(
        settings.open_meteo_forecast_url,
        settings.weather_http_timeout_seconds,
        settings.weather_max_attempts,
    )
    return assemble_services(settings, model=model, provider=provider, notifier=notifier)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
