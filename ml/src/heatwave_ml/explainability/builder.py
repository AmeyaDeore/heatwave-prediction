"""Build, check and version the explainer for a registered model (Part 06 §4, §6-8).

``build`` freezes a background sample of the model's own training split, builds the
explainer, and refuses to save it unless every check passes:

    additivity   SHAP values + expected value = the model's raw output, every class,
                 every validation row; the target-vs-NORMAL sum is log(P(t)/P(NORMAL))
    agreement    the explainer's probabilities are exactly ModelBundle.predict_proba's
    sanity       the hand-picked cases in sanity.py
    latency      p95 of one explained prediction within the policy's request budget

It also records global feature importance on the validation split. That is a
different quantity from the per-prediction explanations the API serves (Part 06 §6),
and is kept for the analytics page and the docs. The test split is never read.
"""

import gc
import json
import time

import numpy as np
import pandas as pd
import yaml

from heatwave_ml.bundle import ModelBundle
from heatwave_ml.evaluation.latency import machine
from heatwave_ml.explainability.explainer import (
    LOG_ODDS,
    MANIFEST_FILE,
    REFERENCE_CLASS,
    ExplainerError,
    HeatwaveExplainer,
    explainer_dir,
)
from heatwave_ml.explainability.sanity import run_sanity_checks
from heatwave_ml.explainability.settings import ExplainabilitySettings
from heatwave_ml.features import FEATURE_COLUMNS, RiskCriteria, SeasonalNormals
from heatwave_ml.registry import ModelRegistry, repo_relative
from heatwave_ml.training.trainer import load_training_data

ADDITIVITY_TOLERANCE = 1e-4
BENCHMARK = {"warmup": 10, "single_row_repeats": 200, "batch_rows": 15, "batch_repeats": 50}


def sample_background(train: pd.DataFrame, rows: int, seed: int) -> pd.DataFrame:
    """A seeded simple random sample of the training split, in record order.

    Simple random, not stratified: the baseline should be the average *day*, so the
    background keeps the training class mix (mostly NORMAL), and a contribution reads
    as "compared with a typical day".
    """
    if rows > len(train):
        raise ExplainerError(f"Background of {rows} rows asked for; train has {len(train)}")
    return train.sample(rows, random_state=seed).sort_values("record_id").reset_index(drop=True)


def consistency(explainer: HeatwaveExplainer, inputs: pd.DataFrame, explained=None) -> dict:
    """The SHAP additivity property (Part 06 §7), measured on ``inputs``.

    ``explained`` is ``explainer.explain_with_parts(inputs)``, if already computed."""
    explanations, parts = explained or explainer.explain_with_parts(inputs)
    phi, raw, ev = parts["shap_values"], parts["raw_output"], parts["expected_value"]
    per_class = np.abs(phi.sum(axis=1) + ev - raw)
    labels = explainer.labels
    ref = labels.index(REFERENCE_CLASS)
    target_error, contract_error = 0.0, 0.0
    for row, e in enumerate(explanations):
        t = labels.index(e.target_class)
        expected = raw[row, t] - raw[row, ref]
        if explainer.engine.quantity == LOG_ODDS:  # softmax: margin gap = log-probability ratio
            proba = parts["probabilities"][row]
            expected_from_p = np.log(proba[t]) - np.log(proba[ref])
            target_error = max(target_error, abs(expected - expected_from_p))
        total = sum(f.contribution for f in e.factors)
        contract_error = max(contract_error, abs(e.baseline + total - e.output))
    bundle_proba = explainer.bundle.predict_proba(inputs).to_numpy()
    return {
        "rows": len(inputs),
        "max_error_per_class": float(per_class.max()),
        "max_error_log_ratio": float(target_error),
        "max_error_contract": float(contract_error),
        "max_error_vs_bundle_proba": float(np.abs(parts["probabilities"] - bundle_proba).max()),
        "tolerance": ADDITIVITY_TOLERANCE,
        # The contract rounds each contribution to 4 decimals, so its sum may drift
        # by up to 7 x 0.00005 from the unrounded output.
        "passed": bool(
            per_class.max() <= ADDITIVITY_TOLERANCE
            and target_error <= ADDITIVITY_TOLERANCE
            and contract_error <= ADDITIVITY_TOLERANCE + 7 * 5e-5
            and np.array_equal(parts["probabilities"], bundle_proba)
        ),
    }


def global_importance(explanations: list) -> dict:
    """Mean |contribution| per feature over many explanations: dataset-level importance.

    NOT an explanation of any single prediction; the API never serves it as one.
    """
    by_feature = {c: [] for c in FEATURE_COLUMNS}
    for e in explanations:
        for f in e.factors:
            by_feature[f.feature].append(abs(f.contribution))
    means = {c: float(np.mean(v)) for c, v in by_feature.items()}
    total = sum(means.values())
    ranked = sorted(means, key=lambda c: -means[c])
    return {
        "rows": len(explanations),
        "split": "validation",
        "note": "dataset-level mean |contribution|; not a per-prediction explanation",
        "features": [
            {
                "feature": c,
                "mean_abs_contribution": round(means[c], 4),
                "share_pct": round(100 * means[c] / total, 1),
            }
            for c in ranked
        ],
    }


def benchmark(explainer: HeatwaveExplainer, rows: pd.DataFrame, budget_ms: float) -> dict:
    """Time ``explain`` end to end (prediction + SHAP + contract + summary)."""

    def timed(inputs: list[pd.DataFrame], warmup: int, repeats: int) -> dict:
        for i in range(warmup):
            explainer.explain(inputs[i % len(inputs)])
        times = []
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            for i in range(repeats):
                started = time.perf_counter()
                explainer.explain(inputs[i % len(inputs)])
                times.append(time.perf_counter() - started)
        finally:
            if gc_was_enabled:
                gc.enable()
        ms = np.asarray(times) * 1000
        return {
            "repeats": repeats,
            "p50_ms": round(float(np.median(ms)), 2),
            "p95_ms": round(float(np.percentile(ms, 95)), 2),
            "mean_ms": round(float(ms.mean()), 2),
        }

    singles = [rows.iloc[[i]] for i in range(min(len(rows), 50))]
    n = BENCHMARK["batch_rows"]
    batches = [rows.iloc[i : i + n] for i in range(0, n * 5, n)]
    single = timed(singles, BENCHMARK["warmup"], BENCHMARK["single_row_repeats"])
    batch = timed(batches, 3, BENCHMARK["batch_repeats"])
    return {
        "machine": machine(),
        "explain_single_row": single,
        "explain_batch": {"rows": n, **batch},
        "budget_p95_ms": budget_ms,
        "passed": single["p95_ms"] <= budget_ms,
        "note": "machine-dependent; re-measure on the serving host (Part 07/18)",
    }


def request_budget_ms(policy_path) -> float:
    """The live-request budget Part 05's policy set: prediction + explanation, p95."""
    with open(policy_path, encoding="utf-8") as fh:
        return float(yaml.safe_load(fh)["gates"]["max_p95_request_ms"])


class ExplainerBuilder:
    def __init__(self, settings: ExplainabilitySettings):
        self.settings = settings
        self.registry = ModelRegistry(settings.registry_dir, settings.runs_dir)
        self.criteria = RiskCriteria.load(settings.risk_config)
        self.normals = SeasonalNormals.load(settings.seasonal_normals)

    def bundle_for(self, model_version: str | None) -> ModelBundle:
        """The production bundle, or a registered model by version."""
        if model_version is None:
            return self.registry.load_production()[0]
        for entry in self.registry.models():
            if entry["model_version"] == model_version:
                return ModelBundle.load(self.registry.resolve(entry))
        raise ExplainerError(f"{model_version} is not a registered (evaluated) model")

    def _data(self, bundle: ModelBundle):
        data = load_training_data(self.settings.dataset_path, self.criteria)
        trained_on = bundle.metadata["training_data"]["sha256"]
        if data.dataset_sha256 != trained_on:
            raise ExplainerError(
                f"{self.settings.dataset_path} (sha256 {data.dataset_sha256[:12]}...) is not the "
                f"dataset {bundle.version} was trained on ({trained_on[:12]}...). The background "
                "must come from the model's own training data."
            )
        return data

    def check(self, explainer: HeatwaveExplainer, data) -> dict:
        """Every deterministic check, re-derivable by ``verify``."""
        explained = explainer.explain_with_parts(data.validation)
        return {
            "consistency": consistency(explainer, data.validation, explained),
            "sanity": run_sanity_checks(explainer, self.normals),
            "global_importance": global_importance(explained[0]),
        }

    def build(self, model_version: str | None = None, *, by: str | None, force: bool = False):
        bundle = self.bundle_for(model_version)
        data = self._data(bundle)
        background = sample_background(
            data.train, self.settings.background_rows, self.settings.seed
        )
        explainer = HeatwaveExplainer.build(
            bundle,
            background,
            source={
                "dataset": repo_relative(data.dataset_path),
                "dataset_sha256": data.dataset_sha256,
                "split": "train",
                "sampling": "simple random, seeded; sorted by record_id",
            },
            seed=self.settings.seed,
        )
        checks = self.check(explainer, data)
        failures = [c["expectation"] for c in checks["sanity"] if not c["passed"]]
        if not checks["consistency"]["passed"]:
            failures.insert(0, f"additivity/agreement: {checks['consistency']}")
        bench = benchmark(explainer, data.train, request_budget_ms(self.settings.selection_policy))
        if not bench["passed"]:
            failures.append(
                f"p95 {bench['explain_single_row']['p95_ms']} ms over the "
                f"{bench['budget_p95_ms']} ms request budget"
            )
        if failures:
            raise ExplainerError("Explainer checks failed: " + "; ".join(failures))

        directory = explainer_dir(self.registry, bundle.version)
        existing = self._existing(directory)
        if existing and not force:
            same = (
                existing["model"]["model_sha256"] == bundle.metadata["model_sha256"]
                and existing["background"]["dataset_sha256"] == data.dataset_sha256
                and existing["background"]["rows"] == len(background)
                and existing["background"]["seed"] == self.settings.seed
            )
            if same:
                return {"status": "unchanged", "directory": directory, "manifest": existing}
            raise ExplainerError(
                f"{directory} holds an explainer built with different inputs; "
                "pass --force to replace it"
            )

        explainer.manifest.update(checks=checks, benchmark=bench, built_by=by)
        explainer.save(directory)
        self.registry.record_event(
            "explainer_built",
            model_version=bundle.version,
            model_sha256=bundle.metadata["model_sha256"],
            explainer_id=explainer.explainer_id,
            background_sha256=explainer.manifest["background"]["sha256"],
            by=by,
            replaced=bool(existing),
        )
        return {"status": "built", "directory": directory, "manifest": explainer.manifest}

    @staticmethod
    def _existing(directory) -> dict | None:
        path = directory / MANIFEST_FILE
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def verify(self, model_version: str | None = None) -> list[str]:
        """Load the saved explainer (hash + probe checks) and re-derive its checks."""
        bundle = self.bundle_for(model_version)
        explainer = HeatwaveExplainer.load(explainer_dir(self.registry, bundle.version), bundle)
        data = self._data(bundle)
        background = sample_background(
            data.train,
            explainer.manifest["background"]["rows"],
            explainer.manifest["background"]["seed"],
        )
        problems = []
        if (
            not background[explainer.background.columns]
            .round(6)
            .equals(explainer.background.round(6))
        ):
            problems.append("the background no longer matches a fresh sample of the training split")
        recorded = explainer.manifest["checks"]
        fresh = self.check(explainer, data)
        if not fresh["consistency"]["passed"]:
            problems.append(f"additivity/agreement failed: {fresh['consistency']}")
        for check in fresh["sanity"]:
            if not check["passed"]:
                problems.append(f"sanity {check['case']}: {check['expectation']}")
        if fresh["global_importance"] != recorded["global_importance"]:
            problems.append("global importance differs from the recorded values")
        if [c["passed"] for c in fresh["sanity"]] != [c["passed"] for c in recorded["sanity"]]:
            problems.append("sanity results differ from the recorded ones")
        return problems
