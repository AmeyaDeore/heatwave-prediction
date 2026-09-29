"""Part 05: score the candidate bundles on the held-out test split, once, and select.

    candidates  the bundles of one training run (+ the production model, if it was
                trained on the same dataset: a retrain is a challenger, not a fresh start)
    → test split scored once per model: per-class and aggregate metrics, confusions,
      calibration, paired bootstrap
    → latency benchmark (training rows)
    → config/model_selection.yaml applied (policy.select), plus the cost sensitivity check
    → ml/registry/evaluations/<evaluation_id>/{report.json, report.md}

Guards (Part 05 §7):
  * The policy file must be committed before the evaluation runs, and the report
    records the commit, so the criteria provably came first.
  * The same comparison (same models, dataset and policy version) is scored once.
    Re-scoring it needs an explicit, recorded reason.
  * ``verify`` re-derives every deterministic number in a report from the bundles
    and the dataset alone, without retraining.
"""

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from heatwave_ml.bundle import ModelBundle, prediction_fingerprint, sha256_file
from heatwave_ml.evaluation.latency import benchmark, machine
from heatwave_ml.evaluation.metrics import (
    SEVERE,
    bootstrap_confusions,
    calibration_metrics,
    classification_metrics,
    expected_cost,
    interval,
    scores_from_confusion,
)
from heatwave_ml.evaluation.policy import Evidence, SelectionPolicy, select
from heatwave_ml.evaluation.report import justification, render_markdown
from heatwave_ml.evaluation.settings import EvaluationSettings
from heatwave_ml.features.criteria import RiskCriteria
from heatwave_ml.features.engineering import model_input
from heatwave_ml.features.schema import TARGET_COLUMN
from heatwave_ml.ingestion.settings import REPO_ROOT
from heatwave_ml.preprocessing.dataset import load_modeling_dataset
from heatwave_ml.preprocessing.split import TEST, TRAIN
from heatwave_ml.registry import ModelRegistry, RegistryError, repo_relative
from heatwave_ml.training.experiment_log import ExperimentLog, new_run_id
from heatwave_ml.training.models import MODEL_FAMILIES
from heatwave_ml.training.trainer import git_state

REPORT_SCHEMA_VERSION = 1
CANDIDATE, CHAMPION = "candidate", "champion"


class EvaluationError(RuntimeError):
    """The evaluation was refused (policy not committed, repeat, wrong dataset...)."""


# -- inputs ------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationData:
    train: pd.DataFrame
    test: pd.DataFrame
    dataset_path: Path
    sha256: str
    manifest: dict
    criteria: RiskCriteria

    @property
    def class_labels(self) -> dict[int, str]:
        return {i: label for label, i in self.criteria.class_to_index.items()}

    def xy(self, split: str) -> tuple[pd.DataFrame, np.ndarray]:
        frame = self.test if split == TEST else self.train
        y = frame[TARGET_COLUMN].map(self.criteria.class_to_index).to_numpy(dtype="int64")
        return model_input(frame), y


def load_evaluation_data(dataset_path: Path, criteria: RiskCriteria) -> EvaluationData:
    """The test split (to score) and the train split (only for latency rows and the
    LinearExplainer background). Checked against the manifest like Part 04's loader."""
    manifest = json.loads(dataset_path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    digest = sha256_file(dataset_path)
    if digest != manifest["sha256"]:
        raise EvaluationError(f"{dataset_path} does not match its manifest's SHA-256")
    if manifest["labeling_rule_version"] != criteria.version:
        raise EvaluationError(
            f"Dataset labelled with {manifest['labeling_rule_version']}, "
            f"config/risk_classes.yaml is {criteria.version}"
        )
    if manifest["class_to_index"] != criteria.class_to_index:
        raise EvaluationError("Dataset class index differs from config/risk_classes.yaml")
    splits = load_modeling_dataset(dataset_path)
    return EvaluationData(splits[TRAIN], splits[TEST], dataset_path, digest, manifest, criteria)


def run_bundle_dirs(experiment_log: Path, run_id: str | None) -> tuple[str, list[Path]]:
    """The packaged bundles of a successful training run, in MODEL_FAMILIES order."""
    run = ExperimentLog(experiment_log).run(run_id)
    if run["status"] != "success":
        raise EvaluationError(f"Training run {run['run_id']} is {run['status']}, not success")
    dirs = [
        REPO_ROOT / run["models"][family]["model_packaged"]["bundle"]
        for family in MODEL_FAMILIES
        if "model_packaged" in run["models"].get(family, {})
    ]
    if not dirs:
        raise EvaluationError(f"Training run {run['run_id']} packaged no models")
    return run["run_id"], dirs


def policy_provenance(path: Path) -> dict:
    """The policy file's hash and the commit that last changed it."""

    def git(*args) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    out = {"path": repo_relative(path), "sha256": sha256_file(path)}
    try:
        last = git("log", "-1", "--format=%H%x09%cI", "--", str(path))
        dirty = bool(git("status", "--porcelain", "--", str(path)))
    except (OSError, subprocess.CalledProcessError):
        last, dirty = "", True
    commit, _, committed_at = last.partition("\t")
    out |= {
        "last_commit": commit or None,
        "committed_at": committed_at or None,
        "uncommitted_changes": dirty or not commit,
    }
    return out


def comparison_key(dataset_sha256: str, model_shas: list[str], policy_version: str) -> str:
    """Identifies "this set of models on this test split under this policy"."""
    payload = json.dumps([dataset_sha256, sorted(model_shas), policy_version])
    return hashlib.sha256(payload.encode()).hexdigest()


# -- scoring (deterministic: shared by run and verify) --------------------------------------


def _bundle_entry(bundle: ModelBundle, role: str) -> dict:
    meta = bundle.metadata
    return {
        "model_version": bundle.version,
        "model_family": bundle.family,
        "run_id": meta["run_id"],
        "role": role,
        "bundle": repo_relative(bundle.directory),
        "model_sha256": meta["model_sha256"],
        "training_data_sha256": meta["training_data"]["sha256"],
        "labeling_rule_version": meta["labeling_rule_version"],
        "hyperparameters": meta["hyperparameters"],
        "validation_f1_macro": meta["validation"]["f1_macro"],
    }


def score(
    bundles: list[ModelBundle],
    data: EvaluationData,
    policy: SelectionPolicy,
    latency: dict[str, dict],
) -> dict:
    """Every deterministic section of the report: metrics, calibration, bootstrap
    intervals, the selection and its sensitivity. ``latency`` is an input (measured
    once, recorded), so re-scoring reproduces the same selection."""
    X, y = data.xy(TEST)
    labels = data.class_labels
    k = len(labels)
    severe = data.criteria.class_to_index[SEVERE]

    candidates, predictions = {}, {}
    for bundle in bundles:
        proba = bundle.predict_proba(X).to_numpy()  # the one pass over the test split
        predictions[bundle.version] = proba.argmax(axis=1)
        candidates[bundle.version] = {
            "test_prediction_fingerprint": prediction_fingerprint(proba),
            "metrics": classification_metrics(y, proba, labels),
            "calibration": calibration_metrics(y, proba, labels, policy.calibration_bins),
        }

    boot = bootstrap_confusions(
        y, predictions, k, policy.bootstrap_resamples, policy.bootstrap_seed
    )
    evidence = []
    for bundle in bundles:
        c = candidates[bundle.version]
        matrix = np.asarray(c["metrics"]["confusion_matrix"]["matrix"])
        samples = scores_from_confusion(boot[bundle.version])
        c["expected_cost"] = round(float(expected_cost(matrix, policy.costs)), 5)
        c["bootstrap"] = {
            "resamples": policy.bootstrap_resamples,
            "confidence": policy.bootstrap_confidence,
            "f1_macro": interval(samples["f1_macro"], policy.bootstrap_confidence),
            "accuracy": interval(samples["accuracy"], policy.bootstrap_confidence),
            f"recall_{SEVERE}": interval(samples["recall"][:, severe], policy.bootstrap_confidence),
            "expected_cost": interval(
                expected_cost(boot[bundle.version], policy.costs), policy.bootstrap_confidence
            ),
        }
        evidence.append(
            Evidence(
                version=bundle.version,
                confusion=matrix,
                boot_confusion=boot[bundle.version],
                severe_predicted_normal=c["metrics"]["failure_modes"]["severe_predicted_normal"],
                top_label_ece=c["calibration"]["top_label"]["ece"],
                p95_request_ms=latency[bundle.version]["request_p95_ms"],
                exact_shap_explainer=latency[bundle.version]["explainer"] is not None,
            )
        )

    selection = select(evidence, policy)
    sensitivity = {}
    for name, costs in policy.sensitivity.items():
        alt = select(evidence, policy, costs)
        sensitivity[name] = {
            "selected": alt["selected"],
            "decided_by": alt.get("decided_by"),
            "agrees": alt["selected"] == selection["selected"],
        }
    return {"candidates": candidates, "selection": selection, "sensitivity": sensitivity}


# -- the evaluation --------------------------------------------------------------------------


class Evaluator:
    def __init__(self, settings: EvaluationSettings):
        self.settings = settings
        self.criteria = RiskCriteria.load(settings.risk_config)
        self.policy = SelectionPolicy.load(settings.selection_policy, self.criteria.classes)
        self.registry = ModelRegistry(settings.registry_dir, settings.runs_dir)

    def _load_bundles(self, dirs: list[Path], data: EvaluationData) -> list[tuple]:
        """(bundle, role, load_ms) for each run bundle, plus the production champion."""
        loaded = []
        for directory in dirs:
            started = time.perf_counter()
            bundle = ModelBundle.load(directory)
            load_ms = (time.perf_counter() - started) * 1000
            if bundle.metadata["training_data"]["sha256"] != data.sha256:
                raise EvaluationError(
                    f"{bundle.version} was trained on dataset "
                    f"{bundle.metadata['training_data']['sha256'][:12]}..., not the current "
                    f"{data.sha256[:12]}...; its test scores would not be comparable"
                )
            loaded.append((bundle, CANDIDATE, load_ms))

        self.notes = []
        pointer = self.registry.production()
        versions = {b.metadata["model_sha256"] for b, _, _ in loaded}
        if pointer and pointer["model_sha256"] not in versions:
            if pointer["training_data"]["sha256"] == data.sha256:
                bundle, _ = self.registry.load_production()
                loaded.append((bundle, CHAMPION, None))
            else:
                # Its training rows may overlap this dataset's test split: not a fair score.
                self.notes.append(
                    f"Production model {pointer['model_version']} was trained on another "
                    "dataset version and is not re-scored on this test split."
                )
        return loaded

    def _refuse_repeat(self, key: str, repeat_reason: str | None) -> dict | None:
        previous = [
            e["evaluation_id"]
            for e in self.registry.events("evaluated")
            if e["comparison_key"] == key
        ]
        if not previous:
            return None
        if not repeat_reason:
            raise EvaluationError(
                f"These models were already scored on this test split under this policy "
                f"(evaluation {previous[-1]}). The test split is read once per comparison "
                "(Part 05 §7): use `heatwave-evaluate verify` to re-check that report, or "
                "pass --repeat-reason to record why a second look is justified."
            )
        return {"previous_evaluations": previous, "reason": repeat_reason}

    def run(
        self,
        run_id: str | None = None,
        *,
        allow_uncommitted_policy: bool = False,
        repeat_reason: str | None = None,
        evaluation_id: str | None = None,
    ) -> dict:
        provenance = policy_provenance(self.settings.selection_policy)
        if provenance["uncommitted_changes"] and not allow_uncommitted_policy:
            raise EvaluationError(
                f"{provenance['path']} has uncommitted changes. Commit the selection "
                "policy before scoring the test split, so the criteria provably come first."
            )
        run_id, dirs = run_bundle_dirs(self.settings.experiment_log, run_id)
        data = load_evaluation_data(self.settings.dataset_path, self.criteria)
        loaded = self._load_bundles(dirs, data)
        bundles = [b for b, _, _ in loaded]
        key = comparison_key(
            data.sha256, [b.metadata["model_sha256"] for b in bundles], self.policy.version
        )
        repeat = self._refuse_repeat(key, repeat_reason)

        X_train, _ = data.xy(TRAIN)
        latency = benchmark(bundles, X_train, self.policy.latency)
        for bundle, _, load_ms in loaded:
            latency[bundle.version]["load_ms"] = None if load_ms is None else round(load_ms, 1)

        scored = score(bundles, data, self.policy, latency)
        _, y_test = data.xy(TEST)
        report = {
            "schema": REPORT_SCHEMA_VERSION,
            "evaluation_id": evaluation_id or new_run_id(),
            "evaluated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
            "training_run": run_id,
            "comparison_key": key,
            "repeat": repeat,
            "dataset": {
                "path": repo_relative(data.dataset_path),
                "sha256": data.sha256,
                "labeling_rule_version": data.criteria.version,
                "split_seed": data.manifest["split"]["seed"],
                "test_rows": int(len(y_test)),
                "test_class_counts": {
                    data.class_labels[i]: int(n)
                    for i, n in enumerate(np.bincount(y_test, minlength=len(data.class_labels)))
                },
            },
            "policy": {"version": self.policy.version, **provenance, "settings": self.policy.raw},
            "notes": self.notes,
            "git": git_state(),
            "machine": machine(),
            "candidates": {},
            "selection": scored["selection"],
            "sensitivity": scored["sensitivity"],
        }
        for bundle, role, _ in loaded:
            report["candidates"][bundle.version] = (
                _bundle_entry(bundle, role)
                | scored["candidates"][bundle.version]
                | {"latency": latency[bundle.version]}
            )
        report["justification"] = justification(report)
        self.registry.save_evaluation(report, render_markdown(report))
        return report

    def verify(self, evaluation_id: str | None = None) -> list[str]:
        """Re-derive a report from its bundles and the dataset. Returns the mismatches."""
        report = self.registry.evaluation(evaluation_id)
        data = load_evaluation_data(self.settings.dataset_path, self.criteria)
        problems = []
        if data.sha256 != report["dataset"]["sha256"]:
            used = report["dataset"]["sha256"]
            return [f"dataset is now {data.sha256[:12]}..., the report used {used[:12]}..."]
        if self.policy.raw != report["policy"]["settings"]:
            return [f"{self.settings.selection_policy} differs from the policy the report used"]

        bundles = []
        for version, c in report["candidates"].items():
            try:
                bundle = ModelBundle.load(self.registry.resolve(c))
            except (RegistryError, OSError) as exc:
                problems.append(f"{version}: {exc}")
                continue
            if bundle.version != version:
                # A reproduced bundle (same SHA-256, new run id): score it under the old name.
                bundle = ModelBundle(
                    bundle.directory, bundle.metadata | {"model_version": version}, bundle.pipeline
                )
            bundles.append(bundle)
        if problems:
            return problems

        latency = {v: c["latency"] for v, c in report["candidates"].items()}
        again = score(bundles, data, self.policy, latency)
        for version, fresh in again["candidates"].items():
            for section, value in fresh.items():
                if report["candidates"][version][section] != value:
                    problems.append(f"{version}: {section} differs from the report")
        for section in ("selection", "sensitivity"):
            if report[section] != again[section]:
                problems.append(f"{section} differs from the report")
        return problems
