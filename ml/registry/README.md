# ml/registry/

The model registry (Part 05): which model is in production, how it got there, and the evaluation evidence behind it. Unlike `ml/artifacts/`, this directory is **committed**. Its files are written by the CLIs, never by hand.

```
production.json                   the production pointer; the backend loads this model
history.jsonl                     append-only: evaluated · promoted · rolled_back events
evaluations/<evaluation_id>/
  report.json                     every metric, the selection trace, provenance
  report.md                       the same, human-readable (comparison table, justification)
```

```sh
uv run heatwave-registry status        # production model + every evaluated model (production / archived)
uv run heatwave-registry verify        # every registered bundle present, hash-intact, loadable
uv run heatwave-registry promote --evaluation <id> [--model <version> --reason "..."]
uv run heatwave-registry rollback --to <version> --reason "..."
```

The pointer references bundles in the git-ignored `ml/artifacts/runs/`. On a fresh clone, run `uv run heatwave-train run` first. Training is reproducible, so the rebuilt bundle has the same SHA-256 and the pointer resolves to it under its new run id.

Full description, the retraining procedure and the current results: [`docs/ml/evaluation.md`](../../docs/ml/evaluation.md).
