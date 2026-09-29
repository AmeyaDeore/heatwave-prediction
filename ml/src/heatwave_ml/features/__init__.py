"""Feature computation shared by training (Part 04) and live inference (Part 07).

Import from here; never reimplement any of it on the serving side:

    from heatwave_ml.features import (
        RiskCriteria, SeasonalNormals, build_features, model_input, preprocessor_for,
    )
"""

from heatwave_ml.features.criteria import RiskCriteria, classify, temperature_deviation
from heatwave_ml.features.engineering import build_features, model_input, wind_at_height
from heatwave_ml.features.normals import SeasonalNormals
from heatwave_ml.features.preprocessor import (
    SCALING_BY_MODEL,
    SeasonalMedianImputer,
    build_preprocessor,
    preprocessor_for,
)
from heatwave_ml.features.schema import (
    FEATURE_COLUMNS,
    FEATURE_DISPLAY,
    FEATURE_LABELS,
    FEATURE_UNITS,
    MONTH_COLUMN,
    RISK_CLASS_LABELS,
    SPLIT_COLUMN,
    TARGET_COLUMN,
)

__all__ = [
    "FEATURE_COLUMNS",
    "FEATURE_DISPLAY",
    "FEATURE_LABELS",
    "FEATURE_UNITS",
    "MONTH_COLUMN",
    "RISK_CLASS_LABELS",
    "SCALING_BY_MODEL",
    "SPLIT_COLUMN",
    "TARGET_COLUMN",
    "RiskCriteria",
    "SeasonalMedianImputer",
    "SeasonalNormals",
    "build_features",
    "build_preprocessor",
    "classify",
    "model_input",
    "preprocessor_for",
    "temperature_deviation",
    "wind_at_height",
]
