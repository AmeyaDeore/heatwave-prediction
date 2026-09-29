"""The Part 04 training pipeline: baseline → imbalance ablation → tuning → final fit → package.

    data/heatwave_dataset.csv (train + validation splits only)
        → per model: stratified k-fold CV on train (baseline, ablation, every tuning candidate)
        → best candidate by CV macro-F1 → refit on the full train split
        → validation-split report → ml/artifacts/runs/<run_id>/<family>/ (bundle)

The test split is dropped at load time and never reaches this module (Part 05 §7).
Every CV evaluation and every packaged model is written to the experiment log.
"""

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import (
    GridSearchCV,
    RandomizedSearchCV,
    StratifiedKFold,
    cross_validate,
)

from heatwave_ml.bundle import (
    library_versions,
    prediction_fingerprint,
    save_bundle,
    scaling_marker,
)
from heatwave_ml.features.criteria import RiskCriteria
from heatwave_ml.features.engineering import model_input
from heatwave_ml.features.schema import FEATURE_COLUMNS, MONTH_COLUMN, TARGET_COLUMN
from heatwave_ml.ingestion.settings import REPO_ROOT
from heatwave_ml.preprocessing.dataset import load_modeling_dataset, sha256_of
from heatwave_ml.preprocessing.split import TRAIN, VALIDATION
from heatwave_ml.training.experiment_log import ExperimentLog, new_run_id
from heatwave_ml.training.metrics import REFIT_METRIC, cv_scoring, holdout_report, summarise_cv
from heatwave_ml.training.models import NO_WEIGHTING, SAMPLE_WEIGHT, ModelSpec, describe_space

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrainingData:
    train: pd.DataFrame
    validation: pd.DataFrame
    dataset_path: Path
    dataset_sha256: str
    manifest: dict
    criteria: RiskCriteria

    @property
    def class_labels(self) -> dict[int, str]:
        return {i: label for label, i in self.criteria.class_to_index.items()}

    def xy(self, split: str) -> tuple[pd.DataFrame, np.ndarray]:
        frame = self.train if split == TRAIN else self.validation
        y = frame[TARGET_COLUMN].map(self.criteria.class_to_index).to_numpy(dtype="int64")
        return model_input(frame), y


def load_training_data(dataset_path: Path, criteria: RiskCriteria) -> TrainingData:
    """Train and validation splits, checked against the dataset's manifest.

    The test split is discarded here, so nothing downstream can tune against it.
    """
    manifest_path = dataset_path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = sha256_of(dataset_path)
    if digest != manifest["sha256"]:
        raise ValueError(
            f"{dataset_path} does not match its manifest's SHA-256; "
            "rebuild it with `heatwave-prepare dataset`"
        )
    if manifest["labeling_rule_version"] != criteria.version:
        raise ValueError(
            f"Dataset labelled with {manifest['labeling_rule_version']}, but "
            f"config/risk_classes.yaml is {criteria.version}; rebuild the dataset"
        )
    if manifest["class_to_index"] != criteria.class_to_index:
        raise ValueError("Dataset class index differs from config/risk_classes.yaml")

    splits = load_modeling_dataset(dataset_path)
    return TrainingData(
        train=splits[TRAIN],
        validation=splits[VALIDATION],
        dataset_path=dataset_path,
        dataset_sha256=digest,
        manifest=manifest,
        criteria=criteria,
    )


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return repr(value)


def _estimator_params(pipeline) -> dict:
    return _jsonable(pipeline.named_steps["clf"].get_params(deep=False))


def _strip_prefix(params: dict) -> dict:
    return {k.removeprefix("clf__"): _jsonable(v) for k, v in params.items()}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def git_state() -> dict:
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def imbalance_description(spec: ModelSpec, y: np.ndarray, class_labels: dict[int, str]) -> dict:
    counts = np.bincount(y, minlength=len(class_labels))
    weights = len(y) / (len(class_labels) * counts)  # sklearn's "balanced" formula
    how = (
        "balanced per-row sample_weight passed to fit()"
        if spec.imbalance == SAMPLE_WEIGHT
        else "estimator class_weight='balanced'"
    )
    return {
        "strategy": spec.imbalance,
        "detail": how,
        "resampling": "none",
        "class_weights_on_train": {
            class_labels[i]: round(float(w), 4) for i, w in enumerate(weights)
        },
    }


@dataclass
class ModelResult:
    family: str
    version: str
    bundle_dir: Path
    baseline_cv: dict
    ablation_cv: dict
    tuned_cv: dict
    best_params: dict
    validation: dict
    fingerprint: str


class Trainer:
    def __init__(
        self,
        data: TrainingData,
        specs: dict[str, ModelSpec],
        *,
        runs_dir: Path,
        experiment_log: ExperimentLog,
        seed: int,
        cv_folds: int,
        n_jobs: int,
        run_id: str | None = None,
    ):
        self.data = data
        self.specs = specs
        self.runs_dir = runs_dir
        self.log = experiment_log
        self.seed = seed
        self.n_jobs = n_jobs
        self.run_id = run_id or new_run_id()
        self.cv_folds = cv_folds
        self.cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=seed)
        self.scoring = cv_scoring(data.class_labels)
        self.X, self.y = data.xy(TRAIN)

    # -- logging -----------------------------------------------------------------------

    def _event(self, event: str, **fields) -> None:
        self.log.append({"event": event, "run_id": self.run_id, **_jsonable(fields)})

    def _trial(self, spec, stage, *, pipeline, search_params, imbalance, cv, fit_seconds, **extra):
        self._event(
            "trial",
            stage=stage,
            model_family=spec.family,
            search_params=search_params,
            estimator_params=_estimator_params(pipeline),
            imbalance_strategy=imbalance,
            cv={"folds": self.cv_folds, "seed": self.seed, "metrics": cv},
            mean_fit_seconds=round(fit_seconds, 4),
            **extra,
        )

    # -- stages ------------------------------------------------------------------------

    def _cross_validate(self, spec: ModelSpec, stage: str, imbalance: str) -> dict:
        pipeline = spec.pipeline(self.seed, imbalance=imbalance)
        result = cross_validate(
            pipeline,
            self.X,
            self.y,
            cv=self.cv,
            scoring=self.scoring,
            params=spec.fit_params(self.y, imbalance=imbalance),
            n_jobs=self.n_jobs,
            error_score="raise",
        )
        cv = summarise_cv(result, self.scoring)
        self._trial(
            spec,
            stage,
            pipeline=pipeline,
            search_params={},
            imbalance=imbalance,
            cv=cv,
            fit_seconds=float(np.mean(result["fit_time"])),
        )
        return cv

    def _tune(self, spec: ModelSpec) -> tuple[dict, dict, int]:
        common = {
            "scoring": self.scoring,
            "refit": False,  # the final fit is its own, logged step
            "cv": self.cv,
            "n_jobs": self.n_jobs,
            "error_score": "raise",
        }
        base = spec.pipeline(self.seed)
        if spec.search == "grid":
            search = GridSearchCV(base, spec.search_space, **common)
        else:
            search = RandomizedSearchCV(
                base, spec.search_space, n_iter=spec.n_iter, random_state=self.seed, **common
            )
        search.fit(self.X, self.y, **spec.fit_params(self.y))
        results = search.cv_results_

        for i, params in enumerate(results["params"]):
            self._trial(
                spec,
                "tuning",
                pipeline=spec.pipeline(self.seed, _strip_prefix(params)),
                search_params=_strip_prefix(params),
                imbalance=spec.imbalance,
                cv=summarise_cv(results, self.scoring, index=i),
                fit_seconds=float(results["mean_fit_time"][i]),
                trial=i,
                rank=int(results[f"rank_test_{REFIT_METRIC}"][i]),
            )
        # Rank 1 on the refit metric; on a tie, the earliest candidate (sklearn's order).
        best = int(np.flatnonzero(results[f"rank_test_{REFIT_METRIC}"] == 1)[0])
        return (
            _strip_prefix(results["params"][best]),
            summarise_cv(results, self.scoring, best),
            best,
        )

    def _final_fit(self, spec: ModelSpec, params: dict):
        started = time.perf_counter()
        pipeline = spec.pipeline(self.seed, params)
        pipeline.fit(self.X, self.y, **spec.fit_params(self.y))
        return pipeline, time.perf_counter() - started

    # -- the run -----------------------------------------------------------------------

    def run(self) -> dict[str, ModelResult]:
        started = time.perf_counter()
        self._event(
            "run_started",
            dataset={
                "path": _relative(self.data.dataset_path),
                "sha256": self.data.dataset_sha256,
                "labeling_rule_version": self.data.criteria.version,
                "split_seed": self.data.manifest["split"]["seed"],
                "train_rows": len(self.data.train),
                "validation_rows": len(self.data.validation),
                "test_rows_used": 0,
            },
            seed=self.seed,
            cv={"method": "StratifiedKFold", "folds": self.cv_folds, "shuffle": True},
            refit_metric=REFIT_METRIC,
            models={
                family: {
                    "search": spec.search,
                    "n_iter": spec.n_iter,
                    "space": describe_space(spec.space),
                    "imbalance_strategy": spec.imbalance,
                }
                for family, spec in self.specs.items()
            },
            n_jobs=self.n_jobs,
            library_versions=library_versions(),
            git=git_state(),
        )
        try:
            results = {family: self._run_model(spec) for family, spec in self.specs.items()}
        except Exception as exc:
            self._event("run_failed", status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        self._event(
            "run_finished",
            status="success",
            duration_seconds=round(time.perf_counter() - started, 1),
            bundles={f: _relative(r.bundle_dir) for f, r in results.items()},
        )
        return results

    def _run_model(self, spec: ModelSpec) -> ModelResult:
        family = spec.family
        log.info("%s: baseline", family)
        baseline = self._cross_validate(spec, "baseline", spec.imbalance)
        ablation = self._cross_validate(spec, "imbalance_ablation", NO_WEIGHTING)

        log.info("%s: tuning (%s search)", family, spec.search)
        tuning_started = time.perf_counter()
        best_params, tuned_cv, best_trial = self._tune(spec)
        self._event(
            "model_selected",
            model_family=family,
            best_trial=best_trial,
            best_params=best_params,
            selected_by=f"highest mean CV {REFIT_METRIC} (ties: earliest candidate)",
            cv=tuned_cv,
            baseline_f1_macro=baseline["f1_macro"]["mean"],
            tuning_seconds=round(time.perf_counter() - tuning_started, 1),
        )

        log.info("%s: final fit on %d training rows", family, len(self.y))
        pipeline, fit_seconds = self._final_fit(spec, best_params)
        X_val, y_val = self.data.xy(VALIDATION)
        proba = pipeline.predict_proba(X_val)
        validation = holdout_report(y_val, proba, self.data.class_labels)
        fingerprint = prediction_fingerprint(proba)

        version = f"{family}-{self.run_id}"
        bundle_dir = self.runs_dir / self.run_id / family
        clf = pipeline.named_steps["clf"]
        train_counts = np.bincount(self.y, minlength=len(self.data.class_labels))
        metadata = save_bundle(
            bundle_dir,
            pipeline,
            {
                "model_version": version,
                "model_family": family,
                "estimator": f"{type(clf).__module__}.{type(clf).__qualname__}",
                "run_id": self.run_id,
                "created_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
                "input_columns": [*FEATURE_COLUMNS, MONTH_COLUMN],
                "feature_columns": list(FEATURE_COLUMNS),
                "target": TARGET_COLUMN,
                "class_labels": {str(i): label for i, label in self.data.class_labels.items()},
                "labeling_rule_version": self.data.criteria.version,
                "preprocessing": {
                    "impute": "SeasonalMedianImputer: same-month training medians for "
                    "rh_pct, wind_ms, solar_mj_m2, precip_mm; Tmax/normal/deviation never imputed",
                    "scale": scaling_marker(pipeline),
                    "fitted_on": "train split",
                },
                "hyperparameters": best_params,
                "estimator_params": _estimator_params(pipeline),
                "imbalance": imbalance_description(spec, self.y, self.data.class_labels),
                "training_data": {
                    "dataset": _relative(self.data.dataset_path),
                    "sha256": self.data.dataset_sha256,
                    "split": TRAIN,
                    "rows": int(len(self.y)),
                    "class_counts": {
                        self.data.class_labels[i]: int(n) for i, n in enumerate(train_counts)
                    },
                    "split_seed": self.data.manifest["split"]["seed"],
                },
                "tuning": {
                    "search": spec.search,
                    "candidates": spec.candidates,
                    "best_trial": best_trial,
                    "cv_folds": self.cv_folds,
                    "refit_metric": REFIT_METRIC,
                    "cv": {k: {"mean": v["mean"], "std": v["std"]} for k, v in tuned_cv.items()},
                    "experiment_log_run_id": self.run_id,
                },
                "validation": validation,
                "reproducibility": {
                    "seed": self.seed,
                    "prediction_fingerprint": fingerprint,
                    "fingerprint_input": "predict_proba on the validation split (float64)",
                    "final_fit_seconds": round(fit_seconds, 3),
                },
                "git": git_state(),
            },
        )
        self._event(
            "model_packaged",
            model_family=family,
            model_version=version,
            bundle=_relative(bundle_dir),
            model_sha256=metadata["model_sha256"],
            prediction_fingerprint=fingerprint,
            validation=validation,
        )
        return ModelResult(
            family=family,
            version=version,
            bundle_dir=bundle_dir,
            baseline_cv=baseline,
            ablation_cv=ablation,
            tuned_cv=tuned_cv,
            best_params=best_params,
            validation=validation,
            fingerprint=fingerprint,
        )
