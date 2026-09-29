"""The modelling schema: feature columns, their units and display names, and the target.

Training (Part 04), SHAP (Part 06) and the backend (Part 07) all import these names
from here. Nothing downstream should spell a feature name out by hand.
"""

# Model input features, in the fixed order every model is trained and served with.
# The first six are the brief's measured variables; the last one is engineered.
FEATURE_COLUMNS = (
    "tmax_c",
    "normal_tmax_c",
    "rh_pct",
    "wind_ms",
    "solar_mj_m2",
    "precip_mm",
    "temp_deviation_c",
)

# Human-readable names, as the brief and the dashboard word them (used by Part 06/12).
FEATURE_LABELS = {
    "tmax_c": "Maximum Temperature",
    "normal_tmax_c": "Seasonal Normal Temperature",
    "rh_pct": "Relative Humidity",
    "wind_ms": "Wind Speed",
    "solar_mj_m2": "Solar Radiation",
    "precip_mm": "Precipitation",
    "temp_deviation_c": "Temperature Deviation",
}

FEATURE_UNITS = {
    "tmax_c": "°C",
    "normal_tmax_c": "°C",
    "rh_pct": "%",
    "wind_ms": "m/s at 2 m",
    "solar_mj_m2": "MJ/m²/day",
    "precip_mm": "mm/day",
    "temp_deviation_c": "°C",
}

# Every wind speed is converted to this height before it becomes a feature
# (NASA POWER reports 2 m, Open-Meteo 10 m; see docs/data/field-availability.md §2.4).
WIND_REFERENCE_HEIGHT_M = 2

# Not model inputs. The imputer groups by month; region and date identify the row.
MONTH_COLUMN = "month"
ID_COLUMNS = ("region_id", "date")

TARGET_COLUMN = "risk_class"
SPLIT_COLUMN = "split"
