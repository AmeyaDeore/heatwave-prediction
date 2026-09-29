"""The experiment log: every training run and every trial, append-only JSON Lines.

Same writer as Part 02's ingestion log (one event per line, flushed and fsynced
as it happens). A training run writes, in order:

    run_started        settings, dataset hash, library versions, git commit
    trial              one per CV evaluation, with ``stage``:
                         baseline            default hyperparameters, chosen imbalance strategy
                         imbalance_ablation  the same defaults with no class weighting
                         tuning              one per search candidate
    model_selected     per model: the best tuning trial and why (refit metric)
    model_packaged     per model: bundle path, version, validation metrics, fingerprint
    run_finished       status and duration  (or run_failed with the error)

Every trial records model family, hyperparameters, imbalance strategy and the
per-fold CV scores, which is enough for Part 05 to reconstruct "why this model"
without retraining. Schema: docs/ml/training.md §6.
"""

import uuid
from datetime import UTC, datetime

from heatwave_ml.ingestion.runlog import IngestionLog

LOG_SCHEMA_VERSION = 1


def new_run_id(now: datetime | None = None) -> str:
    """Sortable by time, and short enough to sit inside a model version id."""
    now = now or datetime.now(UTC)
    return f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


class ExperimentLog(IngestionLog):
    def append(self, event: dict) -> None:
        stamped = {
            "schema": LOG_SCHEMA_VERSION,
            "logged_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **event,
        }
        super().append(stamped)

    def runs(self) -> list[dict]:
        """One summary per run, oldest first: its events grouped by type."""
        runs: dict[str, dict] = {}
        for event in self.events():
            run = runs.setdefault(
                event["run_id"],
                {"run_id": event["run_id"], "status": "incomplete", "trials": [], "models": {}},
            )
            kind = event["event"]
            if kind == "run_started":
                run["started"] = event
            elif kind == "trial":
                run["trials"].append(event)
            elif kind in ("model_selected", "model_packaged"):
                run["models"].setdefault(event["model_family"], {})[kind] = event
            elif kind in ("run_finished", "run_failed"):
                run["status"] = event["status"]
                run["finished"] = event
        return list(runs.values())

    def run(self, run_id: str | None = None) -> dict:
        """A run by id, or the latest run."""
        runs = self.runs()
        if not runs:
            raise LookupError(f"No training runs in {self.path}")
        if run_id is None:
            return runs[-1]
        for run in runs:
            if run["run_id"] == run_id:
                return run
        raise LookupError(f"No run {run_id!r} in {self.path}")
