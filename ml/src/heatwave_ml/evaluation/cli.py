"""``heatwave-evaluate`` and ``heatwave-registry``: the command-line entry points for Part 05.

uv run heatwave-evaluate run [--run ID]        # score a training run's bundles on test, once
uv run heatwave-evaluate show [--evaluation ID]
uv run heatwave-evaluate verify [--evaluation ID]  # re-derive a report from artifacts + dataset

uv run heatwave-registry status                # production pointer + every registered model
uv run heatwave-registry promote --evaluation ID [--model VERSION --reason TEXT]
uv run heatwave-registry rollback --to VERSION --reason TEXT
uv run heatwave-registry verify                # every registered bundle present and intact
"""

import argparse
import logging
import os
import sys

from heatwave_ml.bundle import BundleError, ModelBundle
from heatwave_ml.evaluation.evaluator import EvaluationError, Evaluator
from heatwave_ml.evaluation.report import FAMILY_NAMES
from heatwave_ml.evaluation.settings import EvaluationSettings
from heatwave_ml.registry import REPORT_MD, ModelRegistry, RegistryError, git_user


def _setup() -> EvaluationSettings:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return EvaluationSettings.from_env()


def _print_summary(report: dict) -> None:
    print(
        f"\nEvaluation {report['evaluation_id']} (training run {report['training_run']}, "
        f"{report['dataset']['test_rows']} test rows, policy {report['policy']['version']})\n"
    )
    header = (
        f"{'model':<22}{'accuracy':>10}{'precision':>11}{'recall':>9}{'F1':>9}"
        f"{'SEV rec':>9}{'SEV->N':>8}{'ECE':>8}{'req p95':>10}  gates"
    )
    print(header)
    print("-" * len(header))
    for version, c in report["candidates"].items():
        m, gate = c["metrics"], report["selection"]["gates"][version]
        print(
            f"{FAMILY_NAMES.get(c['model_family'], version):<22}{m['accuracy']:>10.4f}"
            f"{m['precision_macro']:>11.4f}{m['recall_macro']:>9.4f}{m['f1_macro']:>9.4f}"
            f"{m['per_class']['SEVERE_HEATWAVE']['recall']:>9.3f}"
            f"{m['failure_modes']['severe_predicted_normal']:>8d}"
            f"{c['calibration']['top_label']['ece']:>8.4f}"
            f"{c['latency']['request_p95_ms']:>8.1f}ms  {'pass' if gate['passed'] else 'FAIL'}"
        )
    print(
        f"\nSelected: {report['selection']['selected']} ({report['selection'].get('decided_by')})"
    )
    print(f"\n{report['justification']}\n")


def evaluate_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heatwave-evaluate", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="score a training run's bundles on the test split and select")
    run.add_argument("--run", dest="run_id", help="training run id (default: the latest run)")
    run.add_argument("--repeat-reason", help="why these models may be scored on test again")
    run.add_argument(
        "--allow-uncommitted-policy",
        action="store_true",
        help="development only: the report is marked as made under an uncommitted policy",
    )
    for name, text in (("show", "print a report"), ("verify", "re-derive a report")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--evaluation", dest="evaluation_id", help="default: the latest")
    args = parser.parse_args(argv)
    settings = _setup()

    try:
        evaluator = Evaluator(settings)
        if args.command == "run":
            report = evaluator.run(
                args.run_id,
                allow_uncommitted_policy=args.allow_uncommitted_policy,
                repeat_reason=args.repeat_reason,
            )
            _print_summary(report)
            path = settings.registry_dir / "evaluations" / report["evaluation_id"] / REPORT_MD
            print(f"Report -> {path}")
            if report["selection"]["selected"]:
                print(
                    f"Promote with: uv run heatwave-registry promote --evaluation "
                    f"{report['evaluation_id']}"
                )
            return 0 if report["selection"]["selected"] else 1
        if args.command == "show":
            _print_summary(evaluator.registry.evaluation(args.evaluation_id))
            return 0
        report = evaluator.registry.evaluation(args.evaluation_id)
        problems = evaluator.verify(report["evaluation_id"])
        for problem in problems:
            print(f"FAIL {problem}")
        if not problems:
            print(
                f"ok   {report['evaluation_id']}: metrics, calibration, intervals, selection "
                f"and sensitivity re-derived identically for {len(report['candidates'])} models"
            )
        return 1 if problems else 0
    except (EvaluationError, RegistryError, BundleError, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def registry_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heatwave-registry", description="Part 05 model registry")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="production pointer and every registered model")
    sub.add_parser("verify", help="check every registered bundle is present and intact")
    promote = sub.add_parser("promote", help="make an evaluated model the production model")
    promote.add_argument("--evaluation", dest="evaluation_id", required=True)
    promote.add_argument("--model", dest="model_version", help="default: the policy's selection")
    promote.add_argument("--reason", help="required when overriding the policy's selection")
    promote.add_argument("--by", default=git_user(), help="default: git user.name")
    rollback = sub.add_parser("rollback", help="point production back at an earlier model")
    rollback.add_argument("--to", dest="model_version", required=True)
    rollback.add_argument("--reason", required=True)
    rollback.add_argument("--by", default=git_user(), help="default: git user.name")
    args = parser.parse_args(argv)
    settings = _setup()
    registry = ModelRegistry(settings.registry_dir, settings.runs_dir)

    try:
        if args.command in ("promote", "rollback"):
            if not args.by:
                parser.error("--by is required (no git user.name configured)")
            if args.command == "promote":
                pointer = registry.promote(
                    args.evaluation_id,
                    by=args.by,
                    reason=args.reason,
                    model_version=args.model_version,
                )
            else:
                pointer = registry.rollback(args.model_version, by=args.by, reason=args.reason)
            print(f"production -> {pointer['model_version']} (was {pointer['previous']})")
            print(f"pointer    -> {registry.pointer_path}")
            print("Part 06: rebuild the SHAP explainer against this model.")
            return 0
        if args.command == "status":
            pointer = registry.production()
            if pointer:
                print(
                    f"production: {pointer['model_version']}  "
                    f"sha256 {pointer['model_sha256'][:12]}…"
                    f"  since {pointer['changed_at']} by {pointer['changed_by']} "
                    f"({pointer['action']}: {pointer['reason']})"
                )
            else:
                print("production: none")
            for m in registry.models():
                print(
                    f"  {m['status']:<11}{m['model_version']:<48}"
                    f"{'present' if m['present'] else 'MISSING'}  last evaluated "
                    f"{m['last_evaluation']}"
                )
            return 0
        failures = 0
        for m in registry.models():
            try:
                bundle = ModelBundle.load(registry.resolve(m))
                if bundle.metadata["model_sha256"] != m["model_sha256"]:
                    raise BundleError("SHA-256 differs from the registry")
                print(
                    f"ok   {m['status']:<11}{m['model_version']}  ({bundle.directory.name} "
                    f"in run {bundle.metadata['run_id']})"
                )
            except (RegistryError, BundleError) as exc:
                failures += 1
                print(f"FAIL {m['status']:<11}{m['model_version']}: {exc}")
        if registry.production():
            registry.load_production()
            print("ok   production pointer resolves and loads")
        return 1 if failures else 0
    except (RegistryError, BundleError, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(evaluate_main())
