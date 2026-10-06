"""``heatwave-explain``: the command-line entry point for Part 06.

uv run heatwave-explain build [--model VERSION] [--force]   # default: the production model
uv run heatwave-explain verify [--model VERSION]            # reload + re-derive every check
uv run heatwave-explain show [--model VERSION]              # checks, importance, latency
uv run heatwave-explain explain [--rows N] [--json]         # explain validation rows
"""

import argparse
import json
import logging
import os
import sys

from heatwave_ml.bundle import BundleError
from heatwave_ml.explainability.builder import ExplainerBuilder
from heatwave_ml.explainability.explainer import (
    MANIFEST_FILE,
    ExplainerError,
    HeatwaveExplainer,
    explainer_dir,
)
from heatwave_ml.explainability.settings import ExplainabilitySettings
from heatwave_ml.registry import RegistryError, git_user, repo_relative


def _print_manifest(manifest: dict) -> None:
    model, bg = manifest["model"], manifest["background"]
    print(f"explainer  {manifest['explainer_id']}")
    print(f"model      {model['model_version']}  sha256 {model['model_sha256'][:12]}...")
    method = manifest["method"]
    print(
        f"method     shap {manifest['library_versions']['shap']} {method['explainer']} "
        f"({method['feature_perturbation']}), explains {method['quantity']} of the target "
        f"class vs {method['reference_class']}"
    )
    print(
        f"background {bg['rows']} rows of {bg['dataset']} [{bg['split']}], seed {bg['seed']}, "
        f"sha256 {bg['sha256'][:12]}..."
    )
    c = manifest["checks"]["consistency"]
    print(
        f"\nadditivity on {c['rows']} validation rows: max error {c['max_error_per_class']:.2e} "
        f"per class, {c['max_error_log_ratio']:.2e} vs log P-ratio; probabilities identical to "
        f"the bundle: {c['max_error_vs_bundle_proba'] == 0}  -> {'pass' if c['passed'] else 'FAIL'}"
    )
    print("\nsanity checks")
    for s in manifest["checks"]["sanity"]:
        print(
            f"  {'pass' if s['passed'] else 'FAIL'}  {s['case']:<22} {s['risk_class']:<16} "
            f"{s['expectation']}"
        )
    print("\nglobal importance (validation, mean |contribution|; not per prediction)")
    for f in manifest["checks"]["global_importance"]["features"]:
        print(f"  {f['feature']:<18} {f['mean_abs_contribution']:>8.4f}  {f['share_pct']:>5.1f}%")
    b = manifest["benchmark"]
    s, batch = b["explain_single_row"], b["explain_batch"]
    print(
        f"\nlatency    one row p50 {s['p50_ms']} ms / p95 {s['p95_ms']} ms (budget "
        f"{b['budget_p95_ms']} ms); {batch['rows']} rows p50 {batch['p50_ms']} ms"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heatwave-explain", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=text)
        p.add_argument("--model", dest="model_version", help="default: the production model")
        return p

    build = command("build", "build, check and save the explainer for a model")
    build.add_argument(
        "--force", action="store_true", help="replace an explainer built differently"
    )
    build.add_argument("--by", default=git_user(), help="default: git user.name")
    command("verify", "reload the explainer and re-derive every check")
    command("show", "print the explainer's manifest summary")
    explain = command("explain", "explain rows of the validation split")
    explain.add_argument("--rows", type=int, default=3)
    explain.add_argument("--json", action="store_true", help="print the full API contract")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = ExplainabilitySettings.from_env()
    try:
        builder = ExplainerBuilder(settings)
        if args.command == "build":
            result = builder.build(args.model_version, by=args.by, force=args.force)
            print(f"{result['status']}: {repo_relative(result['directory'])}\n")
            _print_manifest(result["manifest"])
            return 0
        if args.command == "verify":
            problems = builder.verify(args.model_version)
            for problem in problems:
                print(f"FAIL {problem}")
            if not problems:
                print(
                    "ok   explainer loads for its model, reproduces its probe, background matches "
                    "the training split, additivity and sanity checks pass, importance re-derived"
                )
            return 1 if problems else 0
        bundle, version = builder.bundle_for(args.model_version)
        directory = explainer_dir(builder.registry, version)
        if args.command == "show":
            if not (directory / MANIFEST_FILE).exists():
                raise ExplainerError(f"No explainer for {version}; run `heatwave-explain build`")
            manifest = json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
            _print_manifest(manifest)
            return 0
        explainer = HeatwaveExplainer.load(directory, bundle)
        rows = builder._data(bundle).validation.head(args.rows)
        for (_, row), e in zip(rows.iterrows(), explainer.explain(rows), strict=True):
            if args.json:
                print(json.dumps(e.to_dict(), indent=2, ensure_ascii=False))
                continue
            print(f"\n{row['region_id']} {row['date']:%Y-%m-%d}  (labelled {row['risk_class']})")
            print(f"  {e.summary}")
            for f in e.factors:
                bar = "#" * round(abs(f.share_pct) / 4)
                print(
                    f"  {f.label:<28}{f.value:>8} {f.unit:<6}{f.contribution:>+8.3f} "
                    f"{f.share_pct:>+6.1f}%  {'+' if f.contribution > 0 else '-'}{bar}"
                )
        return 0
    except (ExplainerError, RegistryError, BundleError, LookupError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
