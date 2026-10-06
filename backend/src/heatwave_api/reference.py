"""Reference data the service reads once at startup: regions, the risk-class
vocabulary and IMD thresholds, the shared label table, and the alert channels.

Everything comes from config/ through heatwave_ml, never from strings typed here,
except the alert channel labels, which only the API and the frontend use.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from heatwave_api.schemas import AlertStatus, Channel, DeliveryStatus, RiskClass
from heatwave_ml.features import FEATURE_DISPLAY, RISK_CLASS_LABELS, RiskCriteria
from heatwave_ml.ingestion.regions import Region, load_regions

CHANNEL_LABELS = {
    "PUBLIC_MOBILE_ALERT": "Public Mobile Alert",
    "GOVERNMENT_PORTAL": "Government Portal",
    "PUBLIC_DISPLAY_BOARDS": "Public Display Boards",
    "EMERGENCY_SERVICES": "Emergency Services",
    "HOSPITALS_HEALTH_CENTRES": "Hospitals & Health Centres",
}
if tuple(CHANNEL_LABELS) != get_args(Channel):  # one vocabulary, checked at import
    raise RuntimeError("CHANNEL_LABELS and schemas.Channel disagree")
if tuple(RISK_CLASS_LABELS) != get_args(RiskClass):
    raise RuntimeError("config/feature_labels.json risk classes and schemas.RiskClass disagree")

ALERT_STATUSES: tuple[str, ...] = get_args(AlertStatus)
DELIVERY_STATUSES: tuple[str, ...] = get_args(DeliveryStatus)
MAX_FORECAST_DAYS = 3


def region_dict(region: Region) -> dict:
    return {
        "id": region.id,
        "name": region.name,
        "district": region.district,
        "state": region.state,
        "zone": region.zone,
        "lat": region.lat,
        "lon": region.lon,
    }


@dataclass
class ReferenceData:
    regions: dict[str, Region]  # monitored now: config/regions.yaml
    criteria: RiskCriteria
    # Every region the database has ever held, for displaying old predictions and
    # alerts of a region since dropped from regions.yaml. Filled at startup.
    known_regions: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, regions_file: Path, risk_config: Path) -> "ReferenceData":
        criteria = RiskCriteria.load(risk_config)
        if criteria.classes != get_args(RiskClass):
            raise ValueError(f"{risk_config}: classes do not match the API vocabulary")
        regions = {r.id: r for r in load_regions(regions_file)}
        unknown_zones = {r.zone for r in regions.values()} - criteria.min_tmax_c.keys()
        if unknown_zones:
            raise ValueError(f"{regions_file}: zones {sorted(unknown_zones)} have no IMD threshold")
        return cls(regions=regions, criteria=criteria)

    def region(self, region_id: str) -> Region | None:
        """A currently monitored region (what new predictions and alerts may target)."""
        return self.regions.get(region_id)

    def display_region(self, region_id: str) -> dict:
        region = self.regions.get(region_id)
        return region_dict(region) if region else self.known_regions[region_id]

    def thresholds(self, zone: str, normal_tmax_c: float) -> tuple[float, float]:
        """The Tmax at which the IMD rule (heatwave-labeling-spec.md) makes a day a
        HEATWAVE and a SEVERE_HEATWAVE, for this zone and seasonal normal.

        A day qualifies by departure (Tmax >= zone minimum and Tmax - normal >= the
        departure threshold) or by absolute Tmax, whichever is lower.
        """
        c = self.criteria
        out = []
        for level in ("HEATWAVE", "SEVERE_HEATWAVE"):
            by_departure = max(c.min_tmax_c[zone], normal_tmax_c + c.departure_c[level])
            out.append(round(min(by_departure, c.absolute_tmax_c[level]), 2))
        return out[0], out[1]

    def as_payload(self) -> dict:
        return {
            "regions": [region_dict(r) for r in self.regions.values()],
            "risk_classes": [{"code": k, "label": v} for k, v in RISK_CLASS_LABELS.items()],
            "alert_statuses": list(ALERT_STATUSES),
            "alert_channels": [{"code": k, "label": v} for k, v in CHANNEL_LABELS.items()],
            "delivery_statuses": list(DELIVERY_STATUSES),
            "features": FEATURE_DISPLAY,
            "max_forecast_days": MAX_FORECAST_DAYS,
        }
