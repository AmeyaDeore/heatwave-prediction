# ml/artifacts/

Output location for trained models and SHAP explainers (Parts 04–06). The contents are git-ignored. Only this README is committed. Rebuild with `uv run heatwave-train run`; training is bit-for-bit reproducible.

```
experiment_log.jsonl              every training run and trial, append-only (Part 04)
runs/<run_id>/<model_family>/
  model.joblib                    fitted Pipeline: preprocessing → estimator
  bundle.json                     the contract: version, dataset hash, features, classes, ...
```

Load a model only through `heatwave_ml.bundle.ModelBundle.load`, which verifies the file hash before unpickling it. The bundle contract is in [`docs/ml/training.md`](../../docs/ml/training.md) §5. Versioning and the production pointer are defined in Part 05.
