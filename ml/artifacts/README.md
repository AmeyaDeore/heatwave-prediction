# ml/artifacts/

Output location for trained models and SHAP explainers (Parts 04–06). The contents are git-ignored. Only this README is committed. Rebuild with `uv run heatwave-train run`; training is bit-for-bit reproducible.

```
experiment_log.jsonl              every training run and trial, append-only (Part 04)
runs/<run_id>/<model_family>/
  model.joblib                    fitted Pipeline: preprocessing → estimator
  bundle.json                     the contract: version, dataset hash, features, classes, ...
```

Load a model only through `heatwave_ml.bundle.ModelBundle.load`, which verifies the file hash before unpickling it. The bundle contract is in [`docs/ml/training.md`](../../docs/ml/training.md) §5.

Which bundle is in production is **not** decided here. It is recorded in the committed registry, [`ml/registry/production.json`](../registry/production.json) (Part 05, [`docs/ml/evaluation.md`](../../docs/ml/evaluation.md)). Don't delete runs: non-production bundles are the archived candidates that a rollback returns to.
