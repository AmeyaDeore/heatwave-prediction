"""The SHAP explainer for a model bundle, and the per-prediction explanation contract.

    explainer = load_production_explainer(registry)      # Part 07, once at startup
    explanations = explainer.explain(features)           # features: build_features() output
    explanations[0].to_dict()                            # prediction + Part 06 §3 contract

``explain`` predicts and explains in one call, from one preprocessing pass, so the
explanation always belongs to the prediction it is returned with. The backend never
touches SHAP.

What is explained (docs/ml/explainability.md §2). A three-class model has one output
per class, but the dashboard needs one signed number per factor where positive
means "more heat risk". Each prediction explains the log-odds of a *risk class
against NORMAL*:

    target = the predicted class, or HEATWAVE when the prediction is NORMAL
    f(x)   = raw_target(x) - raw_NORMAL(x)   = log(P(target) / P(NORMAL)) for XGBoost

A softmax model's class margins are linear in its SHAP values, so this difference is
explained exactly: baseline + sum(contributions) = f(x). A positive contribution
pushes toward the risk class and a negative one toward NORMAL, for every prediction.

The artifact (explainer.json + background.csv, committed under
ml/registry/explainers/<model_version>/) is the frozen background sample plus a
manifest recording the model's SHA-256 and a probe of expected SHAP values. The SHAP
object itself is rebuilt from those at load time rather than pickled, and loading
refuses an artifact built for a different model or one that no longer reproduces
its probe.
"""

import json
import os
import warnings
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

from heatwave_ml.bundle import ModelBundle, library_versions, sha256_file
from heatwave_ml.explainability.summary import format_value, summarize
from heatwave_ml.features.schema import FEATURE_COLUMNS, FEATURE_DISPLAY

EXPLAINER_SCHEMA_VERSION = 1
MANIFEST_FILE = "explainer.json"
BACKGROUND_FILE = "background.csv"
EXPLAINERS_DIR = "explainers"

REFERENCE_CLASS = "NORMAL"
# What a NORMAL prediction is explained against: the next level up ("why not a heatwave").
NORMAL_TARGET = "HEATWAVE"

TREE, LINEAR = "TreeExplainer", "LinearExplainer"
LOG_ODDS, PROBABILITY = "log_odds", "probability"
# The exact SHAP explainer for each model family (Part 06 §2), and what its raw output is.
METHODS = {
    XGBClassifier: (TREE, LOG_ODDS),
    RandomForestClassifier: (TREE, PROBABILITY),
    LogisticRegression: (LINEAR, LOG_ODDS),
}

INCREASES, DECREASES, NEUTRAL = "increases_risk", "decreases_risk", "neutral"
# Rows of the background whose expected SHAP values are stored and re-checked at load.
PROBE_ROWS = 20
PROBE_TOLERANCE = 1e-5
SHAP_CHUNK_ROWS = 50


class ExplainerError(RuntimeError):
    """The explainer is missing, stale (built for another model), or does not reproduce."""


def target_class(risk_class: str) -> str:
    return NORMAL_TARGET if risk_class == REFERENCE_CLASS else risk_class


def explained_quantity(quantity: str, target: str) -> str:
    if quantity == LOG_ODDS:
        return f"log(P({target}) / P({REFERENCE_CLASS}))"
    return f"P({target}) - P({REFERENCE_CLASS})"


# -- the SHAP engine ------------------------------------------------------------------


def float32_floor(values: np.ndarray) -> np.ndarray:
    """The largest float32 <= each value, as float64. For float32 x: x <= result iff x <= value."""
    rounded = values.astype(np.float32)
    too_high = rounded.astype(np.float64) > values
    rounded[too_high] = np.nextafter(rounded[too_high], np.float32(-np.inf))
    return rounded.astype(np.float64)


class _Engine:
    """The SHAP explainer for one bundle's estimator, over one background sample.

    Works on the output of the bundle's ``pre`` step (imputed, and scaled for LR), the
    matrix the estimator actually sees. Returns per-class SHAP values (n, F, C) and the
    estimator's raw per-class output, which they sum to.
    """

    def __init__(self, bundle: ModelBundle, background_inputs: pd.DataFrame):
        import shap  # slow to import; only explainer users pay for it

        self.bundle = bundle
        self.pre = bundle.pipeline.named_steps["pre"]
        self.clf = bundle.pipeline.named_steps["clf"]
        method = METHODS.get(type(self.clf))
        if method is None:
            raise ExplainerError(f"No exact SHAP explainer for {type(self.clf).__name__}")
        self.method, self.quantity = method
        background = self.transform(background_inputs)
        if self.method == LINEAR:
            self._explainer = shap.LinearExplainer(self.clf, background)
        else:
            model = self.clf
            if isinstance(self.clf, XGBClassifier):
                # XGBoost 3 sets enable_categorical=True by default, and SHAP refuses
                # the interventional mode for any such model. These models have no
                # categorical feature, so hand SHAP the booster (same trees) instead.
                booster = self.clf.get_booster()
                if any(t == "c" for t in booster.feature_types or ()):
                    raise ExplainerError("The model has categorical features; not supported")
                model = booster
            self._explainer = shap.TreeExplainer(
                model,
                # A bare DataFrame over 100 rows is silently subsampled to 100 by SHAP.
                # The masker makes it use exactly the frozen background, every row.
                data=shap.maskers.Independent(background, max_samples=len(background)),
                feature_perturbation="interventional",
                model_output="raw",
            )
            if isinstance(self.clf, RandomForestClassifier):
                # sklearn sends x left when float32(x) <= t (t float64), but SHAP's
                # interventional code rounds t to *nearest* float32. A value between
                # t and float32(t) then takes different branches, and one background
                # row doing so shifted every SHAP sum by a leaf's weight (1/60 of a
                # tree's probability). The largest float32 <= t makes both agree.
                model_ = self._explainer.model
                model_.thresholds = float32_floor(model_.thresholds)
        self.expected_value = np.asarray(self._explainer.expected_value, dtype="float64").ravel()

    def transform(self, inputs: pd.DataFrame) -> pd.DataFrame:
        features = self.pre.transform(inputs[self.bundle.input_columns])
        if self.method == TREE:
            # Tree models split on float32 inputs (sklearn casts X to float32, XGBoost's
            # DMatrix stores float32). SHAP gets the same float32 values, so the model
            # and its explanation walk the trees with identical numbers. Without this,
            # Random Forest SHAP sums missed the model's output by up to 1e-4 (see the
            # threshold note in __init__ for the other half of that fix).
            features = features.astype("float32").astype("float64")
        return features

    def shap_values(self, features: pd.DataFrame) -> np.ndarray:
        """(n, F, C). Computed in chunks: SHAP's C extension prints a progress bar on long
        calls. SHAP's own additivity check is off because it re-predicts every row with
        a slow Python tree walk. Additivity is checked explicitly by the builder and the tests."""
        chunks = []
        for start in range(0, len(features), SHAP_CHUNK_ROWS):
            chunk = features.iloc[start : start + SHAP_CHUNK_ROWS]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if self.method == TREE:
                    values = self._explainer.shap_values(chunk, check_additivity=False)
                else:
                    values = self._explainer.shap_values(chunk)
            if isinstance(values, list):  # older SHAP: one (n, F) array per class
                values = np.stack(values, axis=-1)
            chunks.append(np.asarray(values, dtype="float64"))
        return np.concatenate(chunks)

    def raw_output(self, features: pd.DataFrame) -> np.ndarray:
        """What the SHAP values add up to: class margins, or probabilities for RF."""
        if isinstance(self.clf, XGBClassifier):
            return np.asarray(self.clf.predict(features, output_margin=True), dtype="float64")
        if isinstance(self.clf, LogisticRegression):
            return np.asarray(self.clf.decision_function(features), dtype="float64")
        return np.asarray(self.clf.predict_proba(features), dtype="float64")


# -- the contract ---------------------------------------------------------------------


@dataclass(frozen=True)
class Factor:
    rank: int
    feature: str  # internal name, FEATURE_COLUMNS
    label: str  # config/feature_labels.json
    unit: str
    value: float  # the value the model used (after imputation)
    display_value: str  # value + unit at the shared table's precision, e.g. "+7.4 °C"
    imputed: bool  # the input was missing and filled with the training month median
    contribution: float  # signed SHAP value in ``quantity`` units; > 0 raises risk
    share_pct: float  # signed share of the explanation: 100 * contribution / sum(|contributions|)
    direction: str  # increases_risk | decreases_risk | neutral


@dataclass(frozen=True)
class Explanation:
    risk_class: str
    probabilities: dict[str, float]
    target_class: str
    reference_class: str
    quantity: str  # log_odds | probability
    explained: str  # e.g. "log(P(SEVERE_HEATWAVE) / P(NORMAL))"
    baseline: float  # the explained quantity for the average background day
    output: float  # the explained quantity for this row = baseline + sum(contributions)
    factors: tuple[Factor, ...]
    summary: str
    model_version: str
    explainer_id: str

    @property
    def confidence(self) -> float:
        return self.probabilities[self.risk_class]

    def to_dict(self) -> dict:
        """JSON-ready. Part 07 returns this; Part 08 stores ``factors`` row by row."""
        return {
            "risk_class": self.risk_class,
            "confidence": self.confidence,
            "probabilities": dict(self.probabilities),
            "explanation": {
                "target_class": self.target_class,
                "reference_class": self.reference_class,
                "quantity": self.quantity,
                "explained": self.explained,
                "baseline": self.baseline,
                "output": self.output,
                "factors": [asdict(f) for f in self.factors],
                "summary": self.summary,
                "model_version": self.model_version,
                "explainer_id": self.explainer_id,
            },
        }


def _direction(contribution: float) -> str:
    if contribution > 0:
        return INCREASES
    return DECREASES if contribution < 0 else NEUTRAL


def rank_factors(
    contributions: np.ndarray, values: pd.Series, imputed: pd.Series
) -> tuple[Factor, ...]:
    """Every feature, ranked by |contribution| (ties keep the schema order)."""
    total = float(np.abs(contributions).sum())
    order = sorted(range(len(FEATURE_COLUMNS)), key=lambda i: -abs(contributions[i]))
    factors = []
    for rank, i in enumerate(order, start=1):
        name = FEATURE_COLUMNS[i]
        spec = FEATURE_DISPLAY[name]
        c = float(contributions[i])
        factors.append(
            Factor(
                rank=rank,
                feature=name,
                label=spec["label"],
                unit=spec["unit"],
                value=round(float(values[name]), 2),
                display_value=format_value(name, float(values[name])),
                imputed=bool(imputed[name]),
                contribution=round(c, 4),
                share_pct=round(100 * c / total, 1) if total else 0.0,
                direction=_direction(c),
            )
        )
    return tuple(factors)


# -- the explainer --------------------------------------------------------------------


class HeatwaveExplainer:
    """A bundle plus its frozen SHAP explainer. Build with ``build``, load with ``load``."""

    def __init__(self, bundle: ModelBundle, background: pd.DataFrame, manifest: dict):
        self.bundle = bundle
        self.background = background
        self.manifest = manifest
        self.engine = _Engine(bundle, background)
        self.labels = [bundle.class_labels[i] for i in sorted(bundle.class_labels)]

    @property
    def explainer_id(self) -> str:
        return self.manifest["explainer_id"]

    @property
    def model_version(self) -> str:
        return self.bundle.version

    # -- building and loading ---------------------------------------------------------

    @classmethod
    def build(
        cls, bundle: ModelBundle, background: pd.DataFrame, *, source: dict, seed: int
    ) -> "HeatwaveExplainer":
        """A new explainer over ``background`` (model inputs: features + month).

        ``source`` records where the background came from. The manifest is completed
        here, apart from ``background.sha256``, which ``save`` fills in.
        """
        background = background[["record_id", *bundle.input_columns]].reset_index(drop=True)
        engine = _Engine(bundle, background)
        features = engine.transform(background)
        manifest = {
            "explainer_schema": EXPLAINER_SCHEMA_VERSION,
            "explainer_id": None,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": {
                "model_version": bundle.version,
                "model_family": bundle.family,
                "model_sha256": bundle.metadata["model_sha256"],
                "class_labels": bundle.metadata["class_labels"],
            },
            "method": {
                "library": "shap",
                "explainer": engine.method,
                "feature_perturbation": "interventional",
                "quantity": engine.quantity,
                "reference_class": REFERENCE_CLASS,
                "target_rule": f"predicted class; {NORMAL_TARGET} when the prediction is NORMAL",
            },
            "background": {
                "file": BACKGROUND_FILE,
                "rows": len(background),
                "seed": seed,
                **source,
            },
            "expected_value": dict(
                zip(cls._labels(bundle), engine.expected_value.tolist(), strict=True)
            ),
            "probe": {
                "rows": f"the first {PROBE_ROWS} background rows",
                "tolerance": PROBE_TOLERANCE,
                "shap_values": np.round(engine.shap_values(features.iloc[:PROBE_ROWS]), 6).tolist(),
            },
            "library_versions": library_versions() | {"shap": _shap_version()},
        }
        return cls(bundle, background, manifest)

    @staticmethod
    def _labels(bundle: ModelBundle) -> list[str]:
        return [bundle.class_labels[i] for i in sorted(bundle.class_labels)]

    def save(self, directory: Path) -> Path:
        """Write background.csv, then explainer.json with the background's hash and the id."""
        directory.mkdir(parents=True, exist_ok=True)
        background_path = directory / BACKGROUND_FILE
        self.background.to_csv(background_path, index=False, lineterminator="\n")
        digest = sha256_file(background_path)
        self.manifest["background"]["sha256"] = digest
        self.manifest["explainer_id"] = f"{self.model_version}+shap.{digest[:8]}"
        tmp = directory / (MANIFEST_FILE + ".tmp")
        tmp.write_text(json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, directory / MANIFEST_FILE)
        return directory

    @classmethod
    def load(cls, directory: Path, bundle: ModelBundle) -> "HeatwaveExplainer":
        """The explainer saved in ``directory``, for exactly this ``bundle``."""
        manifest_path = Path(directory) / MANIFEST_FILE
        if not manifest_path.exists():
            raise ExplainerError(
                f"No explainer at {directory}. Build it with `uv run heatwave-explain build`."
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("explainer_schema") != EXPLAINER_SCHEMA_VERSION:
            raise ExplainerError(
                f"{manifest_path}: explainer schema {manifest.get('explainer_schema')}, "
                f"this code reads {EXPLAINER_SCHEMA_VERSION}"
            )
        built_for = manifest["model"]["model_sha256"]
        if built_for != bundle.metadata["model_sha256"]:
            raise ExplainerError(
                f"Stale explainer: {manifest_path} was built for "
                f"{manifest['model']['model_version']} "
                f"(sha256 {built_for[:12]}...), not {bundle.version} "
                f"(sha256 {bundle.metadata['model_sha256'][:12]}...). "
                "Rebuild it with `uv run heatwave-explain build`."
            )
        background_path = Path(directory) / manifest["background"]["file"]
        if sha256_file(background_path) != manifest["background"]["sha256"]:
            raise ExplainerError(f"{background_path} does not match the SHA-256 in {manifest_path}")
        background = pd.read_csv(background_path)
        explainer = cls(bundle, background, manifest)
        explainer._check_reproduces()
        return explainer

    def _check_reproduces(self) -> None:
        """The rebuilt SHAP explainer must give the values recorded at build time."""
        expected = np.asarray(self.manifest["probe"]["shap_values"])
        features = self.engine.transform(self.background.iloc[: len(expected)])
        actual = self.engine.shap_values(features)
        tolerance = self.manifest["probe"]["tolerance"]
        if actual.shape != expected.shape or not np.allclose(actual, expected, atol=tolerance):
            worst = (
                float(np.abs(actual - expected).max()) if actual.shape == expected.shape else None
            )
            raise ExplainerError(
                f"Explainer {self.explainer_id} does not reproduce its recorded SHAP values "
                f"(max difference {worst}); library versions now {_shap_version()}, built with "
                f"{self.manifest['library_versions'].get('shap')}. Rebuild it."
            )

    # -- explaining -------------------------------------------------------------------

    def contributions(self, inputs: pd.DataFrame) -> dict:
        """The raw pieces, for tests and diagnostics: per-class SHAP values, the
        estimator's raw output, probabilities and the imputed features."""
        features = self.engine.transform(inputs)
        return {
            "features": features,
            "shap_values": self.engine.shap_values(features),
            "raw_output": self.engine.raw_output(features),
            "expected_value": self.engine.expected_value,
            "probabilities": self.engine.clf.predict_proba(features),
        }

    def explain(self, inputs: pd.DataFrame) -> list[Explanation]:
        """Predict and explain every row of ``inputs`` (features + month, e.g. the
        output of ``build_features``). One Explanation per row, in order."""
        return self.explain_with_parts(inputs)[0]

    def explain_with_parts(self, inputs: pd.DataFrame) -> tuple[list[Explanation], dict]:
        """``explain`` plus the ``contributions`` it was built from, from one SHAP pass."""
        missing = [c for c in self.bundle.input_columns if c not in inputs.columns]
        if missing:
            raise KeyError(f"Model {self.model_version} needs columns {missing}")
        imputed = inputs[list(FEATURE_COLUMNS)].isna().reset_index(drop=True)
        parts = self.contributions(inputs)
        features, phi, proba = parts["features"], parts["shap_values"], parts["probabilities"]
        index = {label: i for i, label in enumerate(self.labels)}
        ref = index[REFERENCE_CLASS]

        out = []
        for row in range(len(features)):
            risk_class = self.labels[int(np.argmax(proba[row]))]
            target = target_class(risk_class)
            t = index[target]
            contributions = phi[row, :, t] - phi[row, :, ref]
            baseline = float(self.engine.expected_value[t] - self.engine.expected_value[ref])
            probabilities = {
                label: round(float(p), 4) for label, p in zip(self.labels, proba[row], strict=True)
            }
            factors = rank_factors(contributions, features.iloc[row], imputed.iloc[row])
            out.append(
                Explanation(
                    risk_class=risk_class,
                    probabilities=probabilities,
                    target_class=target,
                    reference_class=REFERENCE_CLASS,
                    quantity=self.engine.quantity,
                    explained=explained_quantity(self.engine.quantity, target),
                    baseline=round(baseline, 4),
                    output=round(baseline + float(contributions.sum()), 4),
                    factors=factors,
                    summary=summarize(risk_class, probabilities, factors),
                    model_version=self.model_version,
                    explainer_id=self.explainer_id,
                )
            )
        return out, parts

    def explain_one(self, inputs: pd.DataFrame) -> Explanation:
        if len(inputs) != 1:
            raise ValueError(f"explain_one takes one row, got {len(inputs)}")
        return self.explain(inputs)[0]


def _shap_version() -> str:
    import shap

    return shap.__version__


def load_production_explainer(registry, *, check_versions: bool = True) -> HeatwaveExplainer:
    """The production model and its explainer, as one object. What Part 07 calls at startup.

    Refuses an explainer built for any model other than the one production.json names,
    so a promotion or rollback without a rebuild fails loudly instead of explaining
    one model's predictions with another model's explainer.
    """
    bundle, pointer = registry.load_production(check_versions=check_versions)
    return HeatwaveExplainer.load(explainer_dir(registry, pointer["model_version"]), bundle)


def explainer_dir(registry, model_version: str) -> Path:
    return registry.dir / EXPLAINERS_DIR / model_version
