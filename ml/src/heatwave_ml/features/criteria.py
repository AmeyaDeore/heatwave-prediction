"""The heatwave labelling rule (specification: docs/data/heatwave-labeling-spec.md).

Thresholds come from config/risk_classes.yaml and are never written into code. The
rule is versioned: ``labeling_rule_version`` in that file changes whenever the rule
or a threshold changes, and every dataset records the version it was labelled with.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

NORMAL, HEATWAVE, SEVERE_HEATWAVE = "NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"
EXPECTED_CLASSES = (NORMAL, HEATWAVE, SEVERE_HEATWAVE)

# Deviations are rounded to this many decimals before comparison, so that
# 41.5 - 37.0 and 41.49999999 - 36.99999999 land on the same side of 4.5.
DEVIATION_DECIMALS = 2


@dataclass(frozen=True)
class RiskCriteria:
    version: str
    classes: tuple[str, ...]
    min_tmax_c: dict[str, float]
    departure_c: dict[str, float]
    absolute_tmax_c: dict[str, float]

    @classmethod
    def load(cls, path: Path) -> "RiskCriteria":
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        classes = tuple(raw["classes"])
        if classes != EXPECTED_CLASSES:
            raise ValueError(f"{path}: classes must be exactly {EXPECTED_CLASSES}, got {classes}")
        criteria = raw["imd_criteria"]
        return cls(
            version=raw["labeling_rule_version"],
            classes=classes,
            min_tmax_c=dict(criteria["min_tmax_celsius"]),
            departure_c=dict(criteria["departure_from_normal_celsius"]),
            absolute_tmax_c=dict(criteria["absolute_tmax_celsius"]),
        )

    @property
    def class_to_index(self) -> dict[str, int]:
        """Ordinal encoding: 0 = NORMAL, 1 = HEATWAVE, 2 = SEVERE_HEATWAVE."""
        return {label: i for i, label in enumerate(self.classes)}


def temperature_deviation(tmax_c, normal_tmax_c):
    """Temperature Deviation = Maximum Temperature - Seasonal Normal Temperature (°C).

    The one implementation of the engineered feature, shared by the labelling rule,
    the training features and the live inference features.
    """
    return np.round(np.asarray(tmax_c, dtype="float64") - normal_tmax_c, DEVIATION_DECIMALS)


def classify(tmax_c, normal_tmax_c, zone, criteria: RiskCriteria) -> np.ndarray:
    """Apply the IMD daily heatwave rule to each row. Returns class names.

    A row is SEVERE_HEATWAVE or HEATWAVE when either criterion says so, taking the
    more severe of the two:

    1. Departure: Tmax >= the zone's minimum Tmax, and Tmax - normal >= 6.5 (severe)
       or >= 4.5 (heatwave).
    2. Absolute: Tmax >= 47 (severe) or >= 45 (heatwave), whatever the normal.

    Rows with a missing Tmax or normal cannot be labelled; that raises, because a
    silently NORMAL label for missing data would teach the model the wrong thing.
    """
    tmax = np.asarray(tmax_c, dtype="float64")
    normal = np.asarray(normal_tmax_c, dtype="float64")
    zone = np.broadcast_to(np.asarray(zone, dtype=object), tmax.shape)
    if np.isnan(tmax).any() or np.isnan(normal).any():
        raise ValueError("classify() needs Tmax and normal on every row; clean the data first")

    unknown_zones = set(zone) - criteria.min_tmax_c.keys()
    if unknown_zones:
        raise ValueError(f"No min_tmax_celsius for zone(s) {sorted(unknown_zones)}")

    deviation = temperature_deviation(tmax, normal)
    hot_enough = tmax >= np.array([criteria.min_tmax_c[z] for z in zone])

    severity = np.zeros(tmax.shape, dtype="int8")
    severity[hot_enough & (deviation >= criteria.departure_c[HEATWAVE])] = 1
    severity[hot_enough & (deviation >= criteria.departure_c[SEVERE_HEATWAVE])] = 2
    severity = np.maximum(severity, np.where(tmax >= criteria.absolute_tmax_c[HEATWAVE], 1, 0))
    severity = np.maximum(
        severity, np.where(tmax >= criteria.absolute_tmax_c[SEVERE_HEATWAVE], 2, 0)
    )
    return np.array(criteria.classes, dtype=object)[severity]
