"""Hand-picked sanity checks: do explanations match domain intuition? (Part 06 §7)

Each case is a raw weather row, as the live pipeline would receive it, run through
``build_features`` and the explainer, which is the real inference path. The expectations
come from the labelling rule (docs/data/heatwave-labeling-spec.md): labels depend
only on Tmax and its departure from the seasonal normal, so those two must dominate.
Wind is not in the rule. In the data, hot spells come with calmer air, so strong
wind may only ever *lower* the risk.

Run by ``heatwave-explain build`` / ``verify`` (a failing case blocks the build) and by
the test suite (Part 17 §2).
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from heatwave_ml.features import SeasonalNormals, build_features, model_input

REGION, DATE = "mumbai", "2026-05-15"  # a pre-monsoon day in a monitored coastal region
TEMPERATURE = {"tmax_c", "temp_deviation_c"}


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    deviation_c: float  # Tmax = seasonal normal + this
    rh_pct: float
    wind_ms: float
    solar_mj_m2: float = 25.0
    precip_mm: float = 0.0


CASES = (
    Case("extreme_heat", "Tmax 8 °C above normal, dry and calm", 8.0, 35.0, 1.6),
    Case("typical_day", "Tmax at the seasonal normal, humid", 0.3, 70.0, 2.8, 20.0),
    Case("cool_day", "Tmax 3 °C below normal", -3.0, 75.0, 3.0, 15.0, 2.0),
    Case("heatwave_calm", "Tmax 5.5 °C above normal, light wind", 5.5, 45.0, 1.2),
    Case("heatwave_windy", "the same day with a strong 5 m/s wind", 5.5, 45.0, 5.0),
    Case(
        "heat_missing_humidity", "Tmax 7 °C above normal, humidity not reported", 7.0, np.nan, 1.6
    ),
)


def case_rows(normals: SeasonalNormals, cases=CASES) -> pd.DataFrame:
    """The cases as model inputs, computed exactly as live inference computes them."""
    normal = float(normals.lookup([REGION], pd.to_datetime([DATE]))[0])
    raw = pd.DataFrame(
        {
            "region_id": REGION,
            "date": DATE,
            "tmax_c": round(normal + c.deviation_c, 1),
            "rh_pct": c.rh_pct,
            "wind_ms": c.wind_ms,
            "wind_height_m": 2,
            "solar_mj_m2": c.solar_mj_m2,
            "precip_mm": c.precip_mm,
        }
        for c in cases
    )
    return model_input(build_features(raw, normals))


def _factor(explanation, feature: str):
    return next(f for f in explanation.factors if f.feature == feature)


def _top_two(explanation) -> set[str]:
    return {f.feature for f in explanation.factors[:2]}


# Each check: (case, what is expected, test(explanations by case name) -> bool).
Check = tuple[str, str, Callable[[dict], bool]]
CHECKS: tuple[Check, ...] = (
    (
        "extreme_heat",
        "predicted SEVERE_HEATWAVE",
        lambda e: e["extreme_heat"].risk_class == "SEVERE_HEATWAVE",
    ),
    (
        "extreme_heat",
        "top two factors are Temperature Deviation and Maximum Temperature, both raising risk",
        lambda e: (
            _top_two(e["extreme_heat"]) == TEMPERATURE
            and all(f.direction == "increases_risk" for f in e["extreme_heat"].factors[:2])
        ),
    ),
    (
        "typical_day",
        "predicted NORMAL, with Temperature Deviation lowering the risk",
        lambda e: (
            e["typical_day"].risk_class == "NORMAL"
            and _factor(e["typical_day"], "temp_deviation_c").direction == "decreases_risk"
        ),
    ),
    (
        "cool_day",
        "predicted NORMAL, the top factor is a temperature feature lowering the risk",
        lambda e: (
            e["cool_day"].risk_class == "NORMAL"
            and e["cool_day"].factors[0].feature in TEMPERATURE
            and e["cool_day"].factors[0].direction == "decreases_risk"
        ),
    ),
    (
        "heatwave_calm",
        "predicted HEATWAVE or worse, driven by the temperature features",
        lambda e: (
            e["heatwave_calm"].risk_class != "NORMAL"
            and _top_two(e["heatwave_calm"]) == TEMPERATURE
        ),
    ),
    (
        "heatwave_windy",
        "strong wind lowers the risk, and by more than light wind on the same day",
        lambda e: (
            _factor(e["heatwave_windy"], "wind_ms").direction == "decreases_risk"
            and _factor(e["heatwave_windy"], "wind_ms").contribution
            < _factor(e["heatwave_calm"], "wind_ms").contribution
        ),
    ),
    (
        "heat_missing_humidity",
        "still predicted and explained; Relative Humidity is flagged as imputed",
        lambda e: (
            e["heat_missing_humidity"].risk_class != "NORMAL"
            and _factor(e["heat_missing_humidity"], "rh_pct").imputed
            and not _factor(e["heat_missing_humidity"], "tmax_c").imputed
        ),
    ),
)


def run_sanity_checks(explainer, normals: SeasonalNormals) -> list[dict]:
    """Every check with its result, plus the explanation each case produced."""
    explanations = dict(
        zip([c.name for c in CASES], explainer.explain(case_rows(normals)), strict=True)
    )
    results = []
    for case, expectation, test in CHECKS:
        e = explanations[case]
        results.append(
            {
                "case": case,
                "expectation": expectation,
                "passed": bool(test(explanations)),
                "risk_class": e.risk_class,
                "confidence": e.confidence,
                "top_factors": [
                    f"{f.feature} {f.contribution:+.3f} ({f.share_pct:+.1f}%)"
                    for f in e.factors[:3]
                ],
            }
        )
    return results
