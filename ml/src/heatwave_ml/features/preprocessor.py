"""Fitted preprocessing: seasonal imputation, plus scaling for linear models only.

Anything that learns statistics from data lives here, as an sklearn transformer,
so it is fit on the training rows only and then applied unchanged to validation,
test and live rows. Part 04 puts it first in each model's Pipeline, which keeps
it inside cross-validation folds too, and packages the fitted object with the
model. Nothing in Part 03 fits it on the full dataset.

Missing-value strategy, per feature (rationale in docs/data/preprocessing.md):

    tmax_c            never imputed; rows are dropped in cleaning, live requests rejected
    normal_tmax_c     never missing; looked up from the seasonal-normals table
    temp_deviation_c  never imputed; recomputed from the two above
    rh_pct            median of the same calendar month in training data
    wind_ms           median of the same calendar month in training data
    solar_mj_m2       median of the same calendar month in training data
    precip_mm         median of the same calendar month in training data (0 in dry months)
"""

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.validation import check_is_fitted

from heatwave_ml.features.schema import FEATURE_COLUMNS, MONTH_COLUMN

IMPUTED_COLUMNS = ("rh_pct", "wind_ms", "solar_mj_m2", "precip_mm")
NEVER_IMPUTED = tuple(c for c in FEATURE_COLUMNS if c not in IMPUTED_COLUMNS)

# Part 03 §5.5: scaling only where the model family needs it.
SCALING_BY_MODEL = {
    "logistic_regression": True,  # gradient-based and L2-penalised: scale-sensitive
    "random_forest": False,  # splits on thresholds: invariant to monotone rescaling
    "xgboost": False,  # same as random forest
}


class SeasonalMedianImputer(TransformerMixin, BaseEstimator):
    """Fill gaps with the training median of the same calendar month.

    Input: a DataFrame with FEATURE_COLUMNS and ``month``. Output: FEATURE_COLUMNS
    only, in schema order. A month with no training values for a feature falls
    back to that feature's overall training median.
    """

    def __init__(self, columns: tuple[str, ...] = IMPUTED_COLUMNS):
        self.columns = columns

    def _validate(self, X) -> pd.DataFrame:
        if not isinstance(X, pd.DataFrame):
            raise TypeError("SeasonalMedianImputer needs a DataFrame (use model_input(features))")
        missing = [c for c in (*FEATURE_COLUMNS, MONTH_COLUMN) if c not in X.columns]
        if missing:
            raise KeyError(f"Missing columns {missing}")
        return X

    def fit(self, X, y=None):
        X = self._validate(X)
        self.monthly_medians_ = {
            c: {int(m): float(v) for m, v in X.groupby(MONTH_COLUMN)[c].median().dropna().items()}
            for c in self.columns
        }
        self.global_medians_ = {c: float(X[c].median()) for c in self.columns}
        self.n_features_in_ = len(FEATURE_COLUMNS) + 1
        return self

    def transform(self, X):
        check_is_fitted(self, "monthly_medians_")
        X = self._validate(X).copy()
        not_imputable = [c for c in FEATURE_COLUMNS if c not in self.columns]
        bad = X[not_imputable].isna().any()
        if bad.any():
            raise ValueError(f"Cannot impute {list(bad[bad].index)}: these must be present")
        for c in self.columns:
            fill = X[MONTH_COLUMN].map(self.monthly_medians_[c]).fillna(self.global_medians_[c])
            X[c] = X[c].fillna(fill)
        return X[list(FEATURE_COLUMNS)]

    def get_feature_names_out(self, input_features=None):
        return np.array(FEATURE_COLUMNS, dtype=object)


def build_preprocessor(scale: bool) -> Pipeline:
    """Unfitted preprocessing. ``scale=False`` keeps a "passthrough" no-op step, so every
    model's bundle has the same shape (Part 04 §5)."""
    return Pipeline(
        [
            ("impute", SeasonalMedianImputer()),
            ("scale", StandardScaler() if scale else "passthrough"),
        ]
    ).set_output(transform="pandas")


def preprocessor_for(model_family: str) -> Pipeline:
    if model_family not in SCALING_BY_MODEL:
        raise KeyError(f"Unknown model family {model_family!r}; known: {sorted(SCALING_BY_MODEL)}")
    return build_preprocessor(scale=SCALING_BY_MODEL[model_family])
