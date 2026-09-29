"""The one feature-computation step shared by training (Part 04) and live inference (Part 07).

    features = build_features(frame, normals)

``frame`` has the raw landing zone's canonical columns (docs/data/raw-landing-zone.md):
region_id, date, tmax_c, rh_pct, wind_ms, wind_height_m, solar_mj_m2, precip_mm. It
can come from the synthetic set, from NASA POWER + IMD history, or from the
Open-Meteo forecast. Any source goes through this function, so the features can't
drift between training and serving. Part 07 must import it, not reimplement it.
"""

import numpy as np
import pandas as pd

from heatwave_ml.features.criteria import temperature_deviation
from heatwave_ml.features.normals import SeasonalNormals
from heatwave_ml.features.schema import FEATURE_COLUMNS, MONTH_COLUMN, WIND_REFERENCE_HEIGHT_M

REQUIRED_COLUMNS = (
    "region_id",
    "date",
    "tmax_c",
    "rh_pct",
    "wind_ms",
    "wind_height_m",
    "solar_mj_m2",
    "precip_mm",
)

# FAO-56 (Allen et al. 1998, eq. 47) logarithmic wind profile over short grass.
_FAO56_Z0_TERM = (67.8, 5.42)


def wind_at_height(speed_ms, from_height_m, to_height_m: float = WIND_REFERENCE_HEIGHT_M):
    """Convert wind speed between measurement heights with the FAO-56 log profile.

    FAO-56 gives u2 = uz * 4.87 / ln(67.8 z - 5.42), i.e. 10 m → 2 m multiplies by 0.748.
    """
    a, b = _FAO56_Z0_TERM

    def factor(z):
        return 4.87 / np.log(a * np.asarray(z, dtype="float64") - b)

    return np.asarray(speed_ms, dtype="float64") * factor(from_height_m) / factor(to_height_m)


def check_units(frame: pd.DataFrame) -> None:
    """Fail loudly if a column looks like it arrived in the wrong unit.

    Every source already reports °C, %, m/s, MJ/m²/day and mm/day (raw-landing-zone.md).
    A new source in Kelvin, Fahrenheit or a 0-1 humidity fraction would otherwise pass
    straight through and quietly corrupt the features.
    """
    tmax = frame["tmax_c"].dropna()
    if len(tmax) and not 0 < tmax.median() < 60:
        raise ValueError(f"tmax_c median {tmax.median():.1f} is not a °C value (Kelvin/°F?)")
    rh = frame["rh_pct"].dropna()
    if len(rh) >= 10 and rh.max() <= 1.0:
        raise ValueError("rh_pct is at most 1.0: looks like a fraction, expected percent")


def build_features(frame: pd.DataFrame, normals: SeasonalNormals) -> pd.DataFrame:
    """Return ``frame`` with every model feature computed in canonical units.

    - ``normal_tmax_c`` always comes from the seasonal-normals table (an input value,
      if any, is overwritten), so a row's normal never depends on its source.
    - ``wind_ms`` is converted to the 2 m reference height.
    - ``temp_deviation_c`` = tmax_c - normal_tmax_c.
    - ``month`` is added for the seasonal imputer (not a model feature).

    Missing values stay missing; imputation is a fitted step (``preprocessor.py``).
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise KeyError(f"build_features needs columns {missing}")
    check_units(frame)
    heights = frame["wind_height_m"]
    if heights.isna().any():
        raise ValueError("wind_height_m is missing on some rows; the wind speed is ambiguous")

    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["normal_tmax_c"] = normals.lookup(out["region_id"], out["date"])
    out["wind_ms"] = np.round(wind_at_height(out["wind_ms"], heights), 2)
    out["wind_height_m"] = WIND_REFERENCE_HEIGHT_M
    out["temp_deviation_c"] = temperature_deviation(out["tmax_c"], out["normal_tmax_c"])
    out[MONTH_COLUMN] = out["date"].dt.month
    return out


def model_input(features: pd.DataFrame) -> pd.DataFrame:
    """The frame a fitted preprocessor + model expects: the features, plus month."""
    return features[[*FEATURE_COLUMNS, MONTH_COLUMN]]
