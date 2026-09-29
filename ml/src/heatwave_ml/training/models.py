"""The three candidate models: estimator, baseline, search space and imbalance strategy.

Each model is always trained as ``Pipeline([("pre", preprocessor_for(family)),
("clf", estimator)])``, so the fitted imputer (and, for Logistic Regression, the
scaler) sits inside every CV fold and travels with the packaged model.

Rationale for every choice here is in docs/ml/training.md.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace

import numpy as np
from scipy.stats import loguniform, randint, uniform
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

from heatwave_ml.features.preprocessor import preprocessor_for

LOGISTIC_REGRESSION, RANDOM_FOREST, XGBOOST = "logistic_regression", "random_forest", "xgboost"
MODEL_FAMILIES = (LOGISTIC_REGRESSION, RANDOM_FOREST, XGBOOST)

# Imbalance strategies (Part 04 §3.6). No resampling: see docs/ml/training.md §4.
CLASS_WEIGHT = "class_weight"  # estimator's own class_weight="balanced"
SAMPLE_WEIGHT = "sample_weight"  # balanced per-row weights passed to fit()
NO_WEIGHTING = "none"  # the ablation that justifies the choice


@dataclass(frozen=True)
class ModelSpec:
    family: str
    make_estimator: Callable[[int], object]  # seed -> unfitted estimator, single-threaded
    imbalance: str  # CLASS_WEIGHT or SAMPLE_WEIGHT
    search: str  # "grid" or "random"
    space: dict = field(default_factory=dict)  # estimator params, without the "clf__" prefix
    n_iter: int | None = None  # random search only

    def pipeline(self, seed: int, params: dict | None = None, imbalance: str | None = None):
        clf = self.make_estimator(seed)
        if (imbalance or self.imbalance) == CLASS_WEIGHT:
            clf.set_params(class_weight="balanced")
        if params:
            clf.set_params(**params)
        return Pipeline([("pre", preprocessor_for(self.family)), ("clf", clf)])

    def fit_params(self, y, imbalance: str | None = None) -> dict:
        """Extra ``fit()`` arguments. Array-valued ones are sliced per CV fold by sklearn."""
        if (imbalance or self.imbalance) == SAMPLE_WEIGHT:
            return {"clf__sample_weight": compute_sample_weight("balanced", y)}
        return {}

    @property
    def candidates(self) -> int:
        """How many hyperparameter settings the search evaluates."""
        if self.search == "random":
            return self.n_iter
        return int(np.prod([len(values) for values in self.space.values()]))

    @property
    def search_space(self) -> dict:
        return {f"clf__{name}": values for name, values in self.space.items()}


def default_specs() -> dict[str, ModelSpec]:
    return {
        LOGISTIC_REGRESSION: ModelSpec(
            family=LOGISTIC_REGRESSION,
            # lbfgs → multinomial (softmax) with an L2 penalty; deterministic.
            make_estimator=lambda seed: LogisticRegression(max_iter=5000, random_state=seed),
            imbalance=CLASS_WEIGHT,
            search="grid",
            # One real knob, so an exhaustive 1-D grid (17 fits × k folds) is cheap. It
            # reaches 1e5 because CV plateaus from C ≈ 1e3 (barely any penalty): on a
            # tie the earliest, i.e. most regularised, candidate wins.
            space={"C": [float(c) for c in np.logspace(-3, 5, 17)]},
        ),
        RANDOM_FOREST: ModelSpec(
            family=RANDOM_FOREST,
            make_estimator=lambda seed: RandomForestClassifier(random_state=seed, n_jobs=1),
            imbalance=CLASS_WEIGHT,
            search="random",
            space={
                "n_estimators": [200, 400, 600],
                "max_depth": [None, 8, 12, 16, 24],
                "min_samples_leaf": [1, 2, 4, 8],
                "max_features": ["sqrt", 0.5, 0.8, 1.0],
            },
            n_iter=30,  # of 240 combinations
        ),
        XGBOOST: ModelSpec(
            family=XGBOOST,
            make_estimator=lambda seed: XGBClassifier(
                objective="multi:softprob",
                eval_metric="mlogloss",
                tree_method="hist",
                random_state=seed,
                n_jobs=1,
            ),
            # XGBClassifier has no class_weight for multiclass: weights go to fit().
            imbalance=SAMPLE_WEIGHT,
            search="random",
            space={
                "learning_rate": loguniform(0.01, 0.3),
                "n_estimators": randint(100, 801),
                "max_depth": randint(2, 9),
                "min_child_weight": loguniform(0.5, 16),
                "subsample": uniform(0.6, 0.4),
                "colsample_bytree": uniform(0.6, 0.4),
                "reg_lambda": loguniform(0.1, 10),
            },
            n_iter=40,
        ),
    }


def describe_space(space: dict) -> dict:
    """A JSON-safe description of a search space, for the experiment log."""
    out = {}
    for name, values in space.items():
        if isinstance(values, list):
            out[name] = values
        else:  # a frozen scipy distribution
            dist = values.dist.name
            args = [float(a) for a in values.args]
            if dist == "uniform":  # scipy's (loc, scale) → the actual [low, high]
                args = [args[0], args[0] + args[1]]
            if dist == "randint":
                args = [int(args[0]), int(args[1]) - 1]  # inclusive upper bound
            out[name] = {"distribution": dist, "range": args}
    return out


def quick_specs(n_iter: int = 2) -> dict[str, ModelSpec]:
    """Tiny searches for smoke runs and tests; same models and strategies."""
    specs = default_specs()
    return {
        LOGISTIC_REGRESSION: replace(specs[LOGISTIC_REGRESSION], space={"C": [0.1, 1.0, 10.0]}),
        RANDOM_FOREST: replace(
            specs[RANDOM_FOREST],
            space={"n_estimators": [30, 60], "max_depth": [None, 8], "min_samples_leaf": [1, 4]},
            n_iter=n_iter,
        ),
        XGBOOST: replace(
            specs[XGBOOST],
            space={"n_estimators": [30, 60], "max_depth": [3, 5], "learning_rate": [0.1, 0.3]},
            n_iter=n_iter,
        ),
    }
