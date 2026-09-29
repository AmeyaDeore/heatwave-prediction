"""The modelling schema: feature columns, their units and display names, and the target.

Training (Part 04), SHAP (Part 06) and the backend (Part 07) all import these names
from here. Nothing downstream should spell a feature name out by hand.
"""

import json
from pathlib import Path

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

# User-facing names and units live in config/feature_labels.json, the one table the
# backend and frontend read too (Part 06 §5). Loaded here so Python code keeps
# importing FEATURE_LABELS / FEATURE_UNITS from this module.
FEATURE_LABELS_FILE = Path(__file__).resolve().parents[4] / "config" / "feature_labels.json"


def load_feature_labels(path: Path = FEATURE_LABELS_FILE) -> dict:
    """The shared label table, checked against FEATURE_COLUMNS and the class vocabulary."""
    table = json.loads(path.read_text(encoding="utf-8"))
    if tuple(table["features"]) != FEATURE_COLUMNS:
        raise ValueError(
            f"{path}: features must be exactly {FEATURE_COLUMNS} in that order, "
            f"got {tuple(table['features'])}"
        )
    if tuple(table["risk_classes"]) != ("NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"):
        raise ValueError(f"{path}: risk_classes must be NORMAL, HEATWAVE, SEVERE_HEATWAVE")
    return table


_LABEL_TABLE = load_feature_labels()
# Per feature: label, unit (short, for display), unit_detail, decimals, signed.
FEATURE_DISPLAY = _LABEL_TABLE["features"]
FEATURE_LABELS = {name: spec["label"] for name, spec in FEATURE_DISPLAY.items()}
FEATURE_UNITS = {name: spec["unit_detail"] for name, spec in FEATURE_DISPLAY.items()}
# "SEVERE_HEATWAVE" -> "Severe Heatwave". The enum value itself never changes.
RISK_CLASS_LABELS = dict(_LABEL_TABLE["risk_classes"])

# Every wind speed is converted to this height before it becomes a feature
# (NASA POWER reports 2 m, Open-Meteo 10 m; see docs/data/field-availability.md §2.4).
WIND_REFERENCE_HEIGHT_M = 2

# Not model inputs. The imputer groups by month; region and date identify the row.
MONTH_COLUMN = "month"
ID_COLUMNS = ("region_id", "date")

TARGET_COLUMN = "risk_class"
SPLIT_COLUMN = "split"
