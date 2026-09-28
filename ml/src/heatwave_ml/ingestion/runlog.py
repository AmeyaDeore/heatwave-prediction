"""Ingestion metadata log: an append-only JSON Lines file, one event per line.

Each run writes ``run_started``, then one ``chunk`` event per unit of work, then
``run_finished``. Events are flushed as they happen, so a run that crashes still
leaves its started event and every chunk it completed. ``runs()`` reports such a
run as ``incomplete``.
"""

import json
import os
from pathlib import Path


class IngestionLog:
    def __init__(self, path: Path):
        self.path = path

    def append(self, event: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def runs(self) -> list[dict]:
        """One summary per run, oldest first."""
        runs: dict[str, dict] = {}
        for event in self.events():
            run = runs.setdefault(event["run_id"], {"run_id": event["run_id"], "chunks": []})
            if event["event"] == "run_started":
                run |= {k: v for k, v in event.items() if k != "event"}
                run.setdefault("status", "incomplete")
            elif event["event"] == "chunk":
                run["chunks"].append(event)
            elif event["event"] == "run_finished":
                run |= {k: v for k, v in event.items() if k != "event"}
        return list(runs.values())
