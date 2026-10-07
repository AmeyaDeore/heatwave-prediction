"""Reference data read from config/: regions, alert channels, recommended actions.

Loaded once at startup and validated, so a typo in a YAML file stops the service from
starting instead of surfacing on the first request that touches it.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from heatwave_api.config import Settings


@dataclass(frozen=True)
class RegionInfo:
    id: str
    name: str
    district: str
    state: str
    zone: str
    lat: float
    lon: float


MECHANISMS = ("sms", "email", "in_app")


@dataclass(frozen=True)
class Channel:
    id: str
    label: str
    mechanism: str  # how Part 09 delivers it: sms | email | in_app

    def __post_init__(self):
        if self.mechanism not in MECHANISMS:
            raise ValueError(
                f"alert_channels.yaml: channel '{self.id}' has mechanism "
                f"'{self.mechanism}', expected one of {MECHANISMS}"
            )


@dataclass(frozen=True)
class FactorRule:
    feature: str
    direction: str
    top_n: int
    risk_classes: tuple[str, ...]
    action: str


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class Catalog:
    def __init__(
        self,
        *,
        risk_classes: tuple[str, ...],
        regions: list[RegionInfo],
        channels: list[Channel],
        actions_version: str,
        base_actions: dict[str, list[str]],
        factor_rules: list[FactorRule],
    ):
        missing = set(risk_classes) - base_actions.keys()
        if missing:
            raise ValueError(f"recommended_actions.yaml has no actions for {sorted(missing)}")
        self.risk_classes = risk_classes
        self.regions = {r.id: r for r in regions}
        self.channels = {c.id: c for c in channels}
        self.actions_version = actions_version
        self._base = base_actions
        self._rules = factor_rules

    @classmethod
    def load(cls, settings: Settings) -> "Catalog":
        classes = tuple(_yaml(settings.risk_config_path)["classes"])
        regions = [RegionInfo(**r) for r in _yaml(settings.monitored_regions_file)["regions"]]
        channels = [Channel(**c) for c in _yaml(settings.alert_channels_file)["channels"]]
        actions = _yaml(settings.recommended_actions_file)
        rules = []
        for rule in actions.get("by_factor", []):
            unknown = set(rule["for"]) - set(classes)
            if unknown:
                raise ValueError(f"recommended_actions.yaml: unknown risk class(es) {unknown}")
            rules.append(
                FactorRule(
                    feature=rule["feature"],
                    direction=rule["direction"],
                    top_n=int(rule["top_n"]),
                    risk_classes=tuple(rule["for"]),
                    action=rule["action"],
                )
            )
        return cls(
            risk_classes=classes,
            regions=regions,
            channels=channels,
            actions_version=actions["version"],
            base_actions=actions["by_risk_class"],
            factor_rules=rules,
        )

    def recommended_actions(self, risk_class: str, factors: list[dict]) -> list[str]:
        """Base list for the class, then factor-triggered extras. Pure and deterministic."""
        actions = list(self._base[risk_class])
        for rule in self._rules:
            if risk_class not in rule.risk_classes or rule.action in actions:
                continue
            if any(
                f["feature"] == rule.feature
                and f["direction"] == rule.direction
                and f["rank"] <= rule.top_n
                for f in factors
            ):
                actions.append(rule.action)
        return actions
