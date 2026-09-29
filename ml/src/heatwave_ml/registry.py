"""The model registry (Part 05 §5-6): which bundle is in production, and why.

Shared by evaluation (writes) and the backend (reads). Committed to git, unlike
the bundles it points at:

    ml/registry/
      production.json                 THE pointer: the one model the backend serves
      history.jsonl                   append-only: evaluated · promoted · rolled_back
                                      · explainer_built (Part 06)
      evaluations/<evaluation_id>/    report.json + report.md, one per test evaluation
      explainers/<model_version>/     explainer.json + background.csv (Part 06)

Identity. A bundle's ``model_version`` (``<family>-<run_id>``) ties it to its
training run and, through bundle.json, to the dataset hash. Its ``model_sha256``
is its content identity. Bundles are git-ignored, so on a fresh clone the
pointer's path does not exist until ``heatwave-train run`` rebuilds it. Training is
bit-for-bit reproducible, so ``resolve`` then finds the rebuilt bundle by its SHA-256,
under the new run id.

Nothing here deletes a bundle. Candidates that are not promoted stay in
``runs/`` and in the history, which is what a rollback returns to.
"""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from heatwave_ml.bundle import METADATA_FILE, BundleError, ModelBundle
from heatwave_ml.ingestion.runlog import IngestionLog
from heatwave_ml.ingestion.settings import REPO_ROOT

REGISTRY_SCHEMA_VERSION = 1
POINTER_FILE = "production.json"
HISTORY_FILE = "history.jsonl"
EVALUATIONS_DIR = "evaluations"
REPORT_JSON, REPORT_MD = "report.json", "report.md"

PRODUCTION, ARCHIVED = "production", "archived"


class RegistryError(RuntimeError):
    """A registry action was refused, or the registry disagrees with the artifacts."""


def repo_relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict) -> None:
    """Write-then-rename, so a reader never sees a half-written pointer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def git_user() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "config", "user.name"], cwd=REPO_ROOT, capture_output=True, text=True
            ).stdout.strip()
            or None
        )
    except OSError:
        return None


class ModelRegistry:
    def __init__(self, registry_dir: Path, runs_dir: Path):
        self.dir = Path(registry_dir)
        self.runs_dir = Path(runs_dir)
        self.history = IngestionLog(self.dir / HISTORY_FILE)

    # -- evaluations -------------------------------------------------------------------

    @property
    def evaluations_dir(self) -> Path:
        return self.dir / EVALUATIONS_DIR

    def evaluation_ids(self) -> list[str]:
        """Oldest first (ids start with a UTC timestamp)."""
        if not self.evaluations_dir.exists():
            return []
        return sorted(p.parent.name for p in self.evaluations_dir.glob(f"*/{REPORT_JSON}"))

    def evaluation(self, evaluation_id: str | None = None) -> dict:
        """A report by id, or the latest one."""
        ids = self.evaluation_ids()
        if not ids:
            raise LookupError(f"No evaluations in {self.evaluations_dir}")
        evaluation_id = evaluation_id or ids[-1]
        path = self.evaluations_dir / evaluation_id / REPORT_JSON
        if not path.exists():
            raise LookupError(f"No evaluation {evaluation_id!r} in {self.evaluations_dir}")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_evaluation(self, report: dict, markdown: str) -> Path:
        directory = self.evaluations_dir / report["evaluation_id"]
        if (directory / REPORT_JSON).exists():
            raise RegistryError(f"{directory} already exists; evaluation reports are immutable")
        _write_json(directory / REPORT_JSON, report)
        (directory / REPORT_MD).write_text(markdown, encoding="utf-8")
        self._event(
            "evaluated",
            evaluation_id=report["evaluation_id"],
            dataset_sha256=report["dataset"]["sha256"],
            policy_version=report["policy"]["version"],
            comparison_key=report["comparison_key"],
            candidates=[
                {k: c[k] for k in ("model_version", "model_family", "run_id", "bundle")}
                | {"model_sha256": c["model_sha256"]}
                for c in report["candidates"].values()
            ],
            selected=report["selection"]["selected"],
        )
        return directory

    # -- history -----------------------------------------------------------------------

    def _event(self, event: str, **fields) -> None:
        self.history.append(
            {"schema": REGISTRY_SCHEMA_VERSION, "logged_at": _now(), "event": event, **fields}
        )

    def record_event(self, event: str, **fields) -> None:
        """Log an event another part owns, e.g. Part 06's ``explainer_built``."""
        self._event(event, **fields)

    def events(self, kind: str | None = None) -> list[dict]:
        return [e for e in self.history.events() if kind is None or e["event"] == kind]

    def models(self) -> list[dict]:
        """Every bundle that has been evaluated, newest evaluation first, with its status."""
        current = self.production()
        seen: dict[str, dict] = {}
        for event in self.events("evaluated"):
            for c in event["candidates"]:
                seen[c["model_version"]] = c | {"last_evaluation": event["evaluation_id"]}
        out = []
        for version, entry in reversed(seen.items()):
            live = current is not None and current["model_version"] == version
            try:
                present = self.resolve(entry) is not None
            except RegistryError:
                present = False
            out.append(entry | {"status": PRODUCTION if live else ARCHIVED, "present": present})
        return out

    # -- the pointer -------------------------------------------------------------------

    @property
    def pointer_path(self) -> Path:
        return self.dir / POINTER_FILE

    def production(self) -> dict | None:
        if not self.pointer_path.exists():
            return None
        return json.loads(self.pointer_path.read_text(encoding="utf-8"))

    def resolve(self, entry: dict) -> Path:
        """The bundle directory for a registry entry: its recorded path if the model
        there still has the recorded SHA-256, otherwise any bundle of that family
        with the same SHA-256 (a reproduced retrain under a different run id)."""
        recorded = REPO_ROOT / entry["bundle"]
        if (recorded / METADATA_FILE).exists():
            meta = json.loads((recorded / METADATA_FILE).read_text(encoding="utf-8"))
            if meta["model_sha256"] == entry["model_sha256"]:
                return recorded
        for meta_path in sorted(self.runs_dir.glob(f"*/{entry['model_family']}/{METADATA_FILE}")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta["model_sha256"] == entry["model_sha256"]:
                return meta_path.parent
        raise RegistryError(
            f"No bundle with SHA-256 {entry['model_sha256'][:12]}... for {entry['model_version']} "
            f"under {self.runs_dir}. Rebuild it with `uv run heatwave-train run` (training is "
            "reproducible), then `uv run heatwave-registry verify`."
        )

    def load_production(self, *, check_versions: bool = True) -> tuple[ModelBundle, dict]:
        """The production bundle and its pointer. What Part 07 calls at startup."""
        pointer = self.production()
        if pointer is None:
            raise RegistryError(
                f"No production model: {self.pointer_path} is missing. "
                "Run `heatwave-evaluate run`, then `heatwave-registry promote`."
            )
        bundle = ModelBundle.load(self.resolve(pointer), check_versions=check_versions)
        if bundle.metadata["model_sha256"] != pointer["model_sha256"]:
            raise BundleError(f"{bundle.directory} is not the model the pointer records")
        return bundle, pointer

    def _pointer(self, report: dict, version: str, **fields) -> dict:
        c = report["candidates"][version]
        metrics = c["metrics"]
        return {
            "schema": REGISTRY_SCHEMA_VERSION,
            "model_version": version,
            "model_family": c["model_family"],
            "run_id": c["run_id"],
            "bundle": c["bundle"],
            "model_sha256": c["model_sha256"],
            "training_data": {
                "sha256": c["training_data_sha256"],
                "labeling_rule_version": c["labeling_rule_version"],
            },
            "explainer": c["latency"]["explainer"],
            "evaluation": {
                "evaluation_id": report["evaluation_id"],
                "report": repo_relative(self.evaluations_dir / report["evaluation_id"] / REPORT_MD),
                "policy_version": report["policy"]["version"],
                "selected_by_policy": report["selection"]["selected"] == version,
                "test_rows": report["dataset"]["test_rows"],
                # Static per model version; Part 07/14 serve these without recomputing.
                "test_metrics": {
                    k: metrics[k]
                    for k in (
                        "accuracy",
                        "precision_macro",
                        "recall_macro",
                        "f1_macro",
                        "precision_weighted",
                        "recall_weighted",
                        "f1_weighted",
                    )
                }
                | {"per_class": metrics["per_class"]},
                "calibration": {
                    "top_label_ece": c["calibration"]["top_label"]["ece"],
                    "mean_confidence": c["calibration"]["top_label"]["mean_confidence"],
                    "brier_score": c["calibration"]["brier_score"],
                },
            },
            **fields,
        }

    def _set_production(self, pointer: dict, event: str) -> dict:
        self.resolve(pointer)  # refuse to point at a bundle that isn't there
        _write_json(self.pointer_path, pointer)
        self._event(
            event,
            model_version=pointer["model_version"],
            model_sha256=pointer["model_sha256"],
            evaluation_id=pointer["evaluation"]["evaluation_id"],
            by=pointer["changed_by"],
            reason=pointer["reason"],
            override=pointer["override"],
            previous=pointer["previous"],
        )
        return pointer

    def promote(
        self,
        evaluation_id: str,
        *,
        by: str,
        reason: str | None = None,
        model_version: str | None = None,
    ) -> dict:
        """Make a model from an evaluation the production model.

        Defaults to the policy's selection. Promoting a different candidate is an
        override and needs a reason; a candidate that failed a gate is refused.
        """
        report = self.evaluation(evaluation_id)
        selected = report["selection"]["selected"]
        version = model_version or selected
        if version is None:
            raise RegistryError(f"Evaluation {evaluation_id} selected no model; nothing to promote")
        if version not in report["candidates"]:
            raise RegistryError(f"{version} is not a candidate of evaluation {evaluation_id}")
        gate = report["selection"]["gates"][version]
        if not gate["passed"]:
            raise RegistryError(f"{version} failed the policy gates: {'; '.join(gate['failures'])}")
        override = version != selected
        if override and not reason:
            raise RegistryError(
                f"{version} is not the policy's selection ({selected}); give a --reason"
            )
        current = self.production()
        if current and current["model_version"] == version:
            raise RegistryError(f"{version} is already the production model")
        pointer = self._pointer(
            report,
            version,
            action="promote",
            changed_at=_now(),
            changed_by=by,
            reason=reason or f"selected by policy {report['policy']['version']}",
            override=override,
            previous=current["model_version"] if current else None,
        )
        return self._set_production(pointer, "promoted")

    def rollback(self, model_version: str, *, by: str, reason: str) -> dict:
        """Point production back at a previously evaluated model (Part 18 §5)."""
        if not reason:
            raise RegistryError("A rollback needs a --reason")
        current = self.production()
        if current and current["model_version"] == model_version:
            raise RegistryError(f"{model_version} is already the production model")
        evaluations = [
            e["evaluation_id"]
            for e in self.events("evaluated")
            if any(c["model_version"] == model_version for c in e["candidates"])
        ]
        if not evaluations:
            raise RegistryError(f"{model_version} has never been evaluated; promote it instead")
        report = self.evaluation(evaluations[-1])
        gate = report["selection"]["gates"][model_version]
        if not gate["passed"]:
            raise RegistryError(
                f"{model_version} failed the policy gates: {'; '.join(gate['failures'])}"
            )
        pointer = self._pointer(
            report,
            model_version,
            action="rollback",
            changed_at=_now(),
            changed_by=by,
            reason=reason,
            override=model_version != report["selection"]["selected"],
            previous=current["model_version"] if current else None,
        )
        return self._set_production(pointer, "rolled_back")
