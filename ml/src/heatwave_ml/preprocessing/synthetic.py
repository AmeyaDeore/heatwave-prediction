"""Synthetic training dataset generator (the brief's 5,000 simulated-IMD-criteria records).

Specification: docs/data/synthetic-dataset.md. Summary:

1. Draw ``count`` distinct (region, date) slots from the training date range.
2. Look up each slot's seasonal normal from the committed IMD 1991-2020 table.
3. Draw a *true* Tmax anomaly: ordinary day-to-day variability, or (with a
   month-dependent probability) a heat event. A share of rows is deliberately
   placed within ±0.4 °C of a rule threshold (borderline cases).
4. Label each row with the IMD rule (``features.criteria.classify``) on the true Tmax.
5. Draw humidity, wind, solar radiation and precipitation from Mumbai's monthly
   climatology (NASA POWER 2000-2024), shifted physically by the heat anomaly:
   drier air, more sun, less rain on hot days.
6. Add instrument noise to the observed Tmax (σ = 0.3 °C). Near a threshold this can
   put the observed value on the other side of it, as with real measurements.
7. Inject defects: missing values, invalid values and duplicated records, so the
   cleaning step is exercised the same way real data would exercise it.

Deterministic: the same (regions, count, seed, dates, normals, criteria) always
produce the same rows.
"""

import numpy as np
import pandas as pd

from heatwave_ml.features.criteria import RiskCriteria, classify
from heatwave_ml.features.normals import SeasonalNormals
from heatwave_ml.features.schema import TARGET_COLUMN, WIND_REFERENCE_HEIGHT_M
from heatwave_ml.ingestion.regions import Region

# --- Calibration (index 0 = January) -------------------------------------------------
# Day-to-day Tmax variability around the normal: IMD 1991-2020 monthly std, Mumbai cell.
ANOMALY_SD_C = np.array([1.60, 1.85, 1.63, 1.16, 1.07, 2.30, 1.36, 1.17, 1.46, 1.62, 1.13, 1.33])
# NASA POWER 2000-2024 daily values, Mumbai, monthly mean and std.
RH_MEAN = np.array([52.5, 44.9, 44.2, 52.1, 60.8, 79.6, 89.7, 90.2, 88.7, 78.2, 69.5, 60.9])
RH_SD = np.array([11.4, 12.1, 12.0, 7.4, 6.3, 9.1, 2.8, 2.0, 3.6, 8.1, 8.7, 11.4])
WIND_MEAN = np.array([2.00, 2.11, 2.21, 2.28, 2.85, 3.60, 4.02, 3.42, 2.31, 1.75, 1.97, 1.98])
WIND_SD = np.array([0.40, 0.37, 0.37, 0.36, 0.74, 1.20, 0.98, 1.08, 0.93, 0.53, 0.51, 0.49])
SOLAR_MEAN = np.array([17.8, 21.0, 23.5, 25.0, 24.9, 17.3, 13.8, 15.5, 17.1, 18.4, 17.4, 16.5])
SOLAR_SD = np.array([1.8, 1.7, 2.1, 2.0, 3.0, 6.2, 5.3, 4.8, 4.8, 3.5, 2.3, 2.0])
RAIN_DAY_FRACTION = np.array(
    [0.01, 0.03, 0.05, 0.05, 0.17, 0.82, 0.96, 0.96, 0.85, 0.42, 0.11, 0.03]
)
PRECIP_MEAN_MM = np.array([0.03, 0.08, 0.16, 0.10, 1.41, 17.2, 29.1, 18.4, 12.9, 3.39, 0.57, 0.24])
SOLAR_CEILING_MJ = 32.0  # clear-sky daily maximum at ~19° N

# --- Heat events (the enrichment; real Mumbai history has none, see §2.6 of
# field-availability.md). Probability per month that a row is a heat-event day. -------
HEAT_EVENT_PROBABILITY = np.array(
    [0.20, 0.30, 0.45, 0.50, 0.50, 0.12, 0.03, 0.03, 0.05, 0.35, 0.30, 0.20]
)
HEAT_EVENT_BASE_C = 2.5  # event anomaly = base + Gamma(shape, scale)
HEAT_EVENT_GAMMA = (2.0, 1.6)  # mean 3.2 °C on top of the base
# The Gamma tail would otherwise reach 50 °C+. Capping keeps coastal extremes
# plausible; the absolute 45/47 °C branch of the rule is covered by unit tests.
TRUE_TMAX_CEILING_C = 44.0

# Physical response to a positive anomaly (per °C above normal).
RH_DROP_PER_C = 3.0  # hot spells in Mumbai come with dry land winds
SOLAR_GAIN_PER_C = 0.5
WIND_DAMPING_PER_C = 0.03
RAIN_SUPPRESSION_PER_C = 0.6  # rain probability × exp(-0.6 · anomaly)

# --- Injected realism ----------------------------------------------------------------
BORDERLINE_FRACTION = 0.10
BORDERLINE_HALF_WIDTH_C = 0.4
# A Tmax ≈ 37 °C borderline row is only placed where reaching 37 °C takes a
# believable anomaly (not, say, 8.5 °C above a July monsoon normal).
MAX_BORDERLINE_ANOMALY_C = 7.5
TMAX_NOISE_SD_C = 0.3
MISSING_FRACTION = {"rh_pct": 0.02, "wind_ms": 0.02, "solar_mj_m2": 0.02, "precip_mm": 0.02}
MISSING_TMAX_FRACTION = 0.002
CAPPABLE_FRACTION = 0.005  # just outside a bound (e.g. RH 100.5-104): cleaning caps these
INVALID_FRACTION = 0.003  # gross errors (sentinels, sign flips): cleaning drops/imputes these
DUPLICATE_FRACTION = 0.004


class SyntheticGeneratorV1:
    """Callable with Part 02's ``Generator`` signature, so ``SyntheticAdapter`` lands it."""

    version = "imd-sim-v1"

    def __init__(self, normals: SeasonalNormals, criteria: RiskCriteria):
        self.normals = normals
        self.criteria = criteria

    def __call__(self, regions: list[Region], count: int, seed: int, start, end) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        n_duplicates = int(round(count * DUPLICATE_FRACTION))
        n_unique = count - n_duplicates

        # 1. Distinct (region, date) slots.
        days = pd.date_range(start, end, freq="D")
        if n_unique > len(days) * len(regions):
            raise ValueError(f"Only {len(days) * len(regions)} region-days for {n_unique} rows")
        slots = rng.choice(len(days) * len(regions), n_unique, replace=False)
        region_idx, day_idx = np.divmod(slots, len(days))
        region_ids = np.array([r.id for r in regions], dtype=object)[region_idx]
        zones = np.array([r.zone for r in regions], dtype=object)[region_idx]
        dates = days[day_idx]
        month0 = dates.month.to_numpy() - 1

        # 2. Seasonal normal.
        normal = self.normals.lookup(region_ids, dates)

        # 3. True anomaly: background variability, heat events, borderline placements.
        anomaly = rng.normal(0.0, ANOMALY_SD_C[month0])
        event = rng.random(n_unique) < HEAT_EVENT_PROBABILITY[month0]
        anomaly[event] = HEAT_EVENT_BASE_C + rng.gamma(*HEAT_EVENT_GAMMA, event.sum())
        anomaly = self._place_borderline(rng, anomaly, normal, zones)
        true_tmax = np.round(np.minimum(normal + anomaly, TRUE_TMAX_CEILING_C), 1)

        # 4. Label from the rule, on the true value.
        label = classify(true_tmax, normal, zones, self.criteria)

        # 5. Other variables from monthly climatology, shifted by the heat anomaly.
        heat = np.clip(true_tmax - normal, 0.0, None)
        rh = np.clip(rng.normal(RH_MEAN[month0] - RH_DROP_PER_C * heat, RH_SD[month0]), 5, 100)
        solar = np.clip(
            rng.normal(SOLAR_MEAN[month0] + SOLAR_GAIN_PER_C * heat, SOLAR_SD[month0]),
            0,
            SOLAR_CEILING_MJ,
        )
        shape = (WIND_MEAN[month0] / WIND_SD[month0]) ** 2
        wind = rng.gamma(shape, WIND_SD[month0] ** 2 / WIND_MEAN[month0])
        wind = np.clip(wind * (1 - WIND_DAMPING_PER_C * heat), 0.2, None)
        rains = rng.random(n_unique) < RAIN_DAY_FRACTION[month0] * np.exp(
            -RAIN_SUPPRESSION_PER_C * heat
        )
        wet_day_mean = PRECIP_MEAN_MM[month0] / RAIN_DAY_FRACTION[month0]
        precip = np.where(rains, rng.gamma(0.7, wet_day_mean / 0.7), 0.0)

        # 6. Observed Tmax carries instrument noise.
        observed_tmax = true_tmax + rng.normal(0.0, TMAX_NOISE_SD_C, n_unique)

        frame = pd.DataFrame(
            {
                "region_id": region_ids,
                "date": dates,
                "tmax_c": np.round(observed_tmax, 1),
                "normal_tmax_c": normal,
                "rh_pct": np.round(rh, 1),
                "wind_ms": np.round(wind, 2),
                "wind_height_m": WIND_REFERENCE_HEIGHT_M,
                "solar_mj_m2": np.round(solar, 2),
                "precip_mm": np.round(precip, 1),
                TARGET_COLUMN: label,
            }
        )

        # 7. Defects, then duplicates, then shuffle and number the records.
        frame = self._inject_defects(rng, frame)
        frame = self._inject_duplicates(rng, frame, n_duplicates)
        frame = frame.iloc[rng.permutation(len(frame))].reset_index(drop=True)
        frame.insert(0, "record_id", np.arange(len(frame)))
        return frame

    def _place_borderline(self, rng, anomaly, normal, zones) -> np.ndarray:
        """Move a share of rows to within ±0.4 °C of a threshold the rule actually tests."""
        anomaly = anomaly.copy()
        min_tmax = np.array([self.criteria.min_tmax_c[z] for z in zones])
        heatwave = self.criteria.departure_c["HEATWAVE"]
        severe = self.criteria.departure_c["SEVERE_HEATWAVE"]

        # Departure boundary (4.5 / 6.5 °C above normal) needs Tmax above the zone minimum.
        on_departure = normal + heatwave - BORDERLINE_HALF_WIDTH_C >= min_tmax
        # Minimum-Tmax boundary (Tmax ≈ 37 °C with a big departure) needs a believable anomaly.
        gap = min_tmax - normal
        on_minimum = ~on_departure & (gap >= heatwave) & (gap <= MAX_BORDERLINE_ANOMALY_C)
        eligible = np.flatnonzero(on_departure | on_minimum)

        n_border = min(int(round(len(anomaly) * BORDERLINE_FRACTION)), len(eligible))
        chosen = np.sort(rng.choice(eligible, n_border, replace=False))
        jitter = rng.uniform(-BORDERLINE_HALF_WIDTH_C, BORDERLINE_HALF_WIDTH_C, n_border)
        pick_severe = rng.random(n_border) < 0.5
        departure = np.where(pick_severe, severe, heatwave) + jitter
        minimum = gap[chosen] + jitter
        anomaly[chosen] = np.where(on_departure[chosen], departure, minimum)
        return anomaly

    @staticmethod
    def _inject_defects(rng, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        n = len(frame)
        for column, fraction in MISSING_FRACTION.items():
            frame.loc[rng.random(n) < fraction, column] = np.nan
        frame.loc[rng.random(n) < MISSING_TMAX_FRACTION, "tmax_c"] = np.nan

        # Just outside a bound: cleaning caps these.
        cappable = np.flatnonzero(rng.random(n) < CAPPABLE_FRACTION)
        for i in cappable:
            column, value = [
                ("rh_pct", rng.uniform(100.1, 104.9)),
                ("wind_ms", -rng.uniform(0.01, 0.4)),
                ("solar_mj_m2", -rng.uniform(0.01, 0.4)),
                ("precip_mm", -rng.uniform(0.01, 0.4)),
            ][rng.integers(4)]
            frame.loc[frame.index[i], column] = round(value, 2)

        # Gross errors: sentinels leaking through, sign flips, unit slips.
        invalid = np.flatnonzero(rng.random(n) < INVALID_FRACTION)
        for i in invalid:
            column, value = [
                ("tmax_c", 99.9),  # IMD's no-data sentinel
                ("rh_pct", 999.0),
                ("wind_ms", -3.0),
                ("solar_mj_m2", -999.0),  # NASA POWER's no-data sentinel
                ("precip_mm", -999.0),
            ][rng.integers(5)]
            frame.loc[frame.index[i], column] = value
        return frame

    @staticmethod
    def _inject_duplicates(rng, frame: pd.DataFrame, n_duplicates: int) -> pd.DataFrame:
        """Re-landed records for an existing region+date. Half are exact copies; half carry
        a slightly different reading (the case where "which copy is right?" matters)."""
        source = frame.iloc[rng.choice(len(frame), n_duplicates, replace=False)].copy()
        altered = rng.random(n_duplicates) < 0.5
        source.loc[altered, "rh_pct"] = np.round(
            np.clip(source.loc[altered, "rh_pct"] + rng.normal(0, 3, altered.sum()), 5, 100), 1
        )
        return pd.concat([frame, source], ignore_index=True)
