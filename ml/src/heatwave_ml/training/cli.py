"""``heatwave-train``: the command-line entry point for Part 04.

    uv run heatwave-train run                  # all three models → ml/artifacts/runs/<run_id>/
    uv run heatwave-train run --models xgboost # a subset
    uv run heatwave-train run --quick          # tiny searches, for a smoke test
    uv run heatwave-train summary [--run ID]   # the comparison table, from the experiment log
    uv run heatwave-train verify [--run ID]    # reload each bundle and re-check its contract

Training never reads the test split; Part 05 evaluates on it, once.
"""

import argparse
import logging
import os
import sys

from heatwave_ml.bundle import BundleError, ModelBundle, prediction_fingerprint
from heatwave_ml.features.criteria import RiskCriteria
from heatwave_ml.ingestion.settings import REPO_ROOT
from heatwave_ml.preprocessing.split import VALIDATION
from heatwave_ml.training.experiment_log import ExperimentLog
from heatwave_ml.training.models import MODEL_FAMILIES, default_specs, quick_specs
from heatwave_ml.training.settings import TrainingSettings
from heatwave_ml.training.trainer import Trainer, load_training_data

log = logging.getLogger("heatwave_ml.train")


def _run(settings: TrainingSettings, args) -> int:
    specs = quick_specs() if args.quick else default_specs()
    specs = {family: specs[family] for family in args.models}
    data = load_training_data(settings.dataset_path, RiskCriteria.load(settings.risk_config))
    trainer = Trainer(
        data,
        specs,
        runs_dir=settings.runs_dir,
        experiment_log=ExperimentLog(settings.experiment_log),
        seed=settings.random_seed,
        cv_folds=settings.cv_folds,
        n_jobs=settings.n_jobs,
    )
    print(f"Training run {trainer.run_id} on {len(data.train)} rows, {settings.cv_folds}-fold CV")
    trainer.run()
    print(f"Bundles -> {settings.runs_dir / trainer.run_id}")
    print(f"Log     -> {settings.experiment_log}")
    return _summary(settings, trainer.run_id)


def _summary(settings: TrainingSettings, run_id: str | None) -> int:
    run = ExperimentLog(settings.experiment_log).run(run_id)
    duration = run.get("finished", {}).get("duration_seconds")
    print(f"\nRun {run['run_id']}: {run['status']}" + (f", {duration} s" if duration else ""))

    def cv(family, stage):
        trials = [t for t in run["trials"] if t["model_family"] == family and t["stage"] == stage]
        return trials[0]["cv"]["metrics"] if trials else None

    header = (
        f"{'model':<21}{'baseline':>10}{'no-weight':>11}{'tuned':>9}{'sd':>7}"
        f"{'val F1':>9}{'val acc':>9}{'val SEV rec':>13}"
    )
    print("\nMacro-F1: CV on train (baseline / without class weighting / tuned); then validation")
    print(header)
    print("-" * len(header))
    for family, models in run["models"].items():
        selected, packaged = models.get("model_selected"), models.get("model_packaged")
        if not (selected and packaged):
            continue
        val = packaged["validation"]
        print(
            f"{family:<21}{cv(family, 'baseline')['f1_macro']['mean']:>10.4f}"
            f"{cv(family, 'imbalance_ablation')['f1_macro']['mean']:>11.4f}"
            f"{selected['cv']['f1_macro']['mean']:>9.4f}{selected['cv']['f1_macro']['std']:>7.4f}"
            f"{val['f1_macro']:>9.4f}{val['accuracy']:>9.4f}"
            f"{val['per_class']['SEVERE_HEATWAVE']['recall']:>13.4f}"
        )
    print("\nBest hyperparameters:")
    for family, models in run["models"].items():
        if "model_selected" in models:
            print(f"  {family}: {models['model_selected']['best_params']}")
    return 0 if run["status"] == "success" else 1


def _verify(settings: TrainingSettings, run_id: str | None) -> int:
    run = ExperimentLog(settings.experiment_log).run(run_id)
    data = load_training_data(settings.dataset_path, RiskCriteria.load(settings.risk_config))
    X_val, _ = data.xy(VALIDATION)
    failures = 0
    for family, models in run["models"].items():
        packaged = models.get("model_packaged")
        if not packaged:
            continue
        try:
            bundle = ModelBundle.load(REPO_ROOT / packaged["bundle"])
            if bundle.metadata["training_data"]["sha256"] != data.dataset_sha256:
                raise BundleError("trained on a different dataset version than the current one")
            fingerprint = prediction_fingerprint(bundle.predict_proba(X_val).to_numpy())
            if fingerprint != bundle.metadata["reproducibility"]["prediction_fingerprint"]:
                raise BundleError("validation predictions differ from those recorded at training")
        except (BundleError, KeyError) as exc:
            failures += 1
            print(f"FAIL {family}: {exc}")
            continue
        print(f"ok   {bundle.version}: hash, versions, features, classes, predictions")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heatwave-train", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="train, tune and package the candidate models")
    run.add_argument(
        "--models",
        type=lambda s: [m.strip() for m in s.split(",")],
        default=list(MODEL_FAMILIES),
        help=f"comma-separated subset of {','.join(MODEL_FAMILIES)}",
    )
    run.add_argument("--quick", action="store_true", help="tiny search spaces (smoke test)")
    for name, text in (
        ("summary", "print a run's results"),
        ("verify", "re-check a run's bundles"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--run", dest="run_id", help="run id (default: the latest run)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = TrainingSettings.from_env()

    if args.command == "run":
        unknown = set(args.models) - set(MODEL_FAMILIES)
        if unknown:
            parser.error(f"unknown models {sorted(unknown)}; choose from {MODEL_FAMILIES}")
        return _run(settings, args)
    try:
        if args.command == "summary":
            return _summary(settings, args.run_id)
        return _verify(settings, args.run_id)
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
