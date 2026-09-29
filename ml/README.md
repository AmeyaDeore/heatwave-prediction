# ml/

Parts 02–06: data collection, preprocessing and feature engineering, model training (Logistic Regression / Random Forest / XGBoost), evaluation and selection, and SHAP explainability.

- Package: `src/heatwave_ml/`
- Tests: `tests/`
- Trained artifacts: `artifacts/`. These are git-ignored and produced by the pipeline.
- Config: copy `.env.example` to `.env`. Risk thresholds come from `config/risk_classes.yaml`.

```sh
uv sync --package heatwave-ml
uv run pytest ml/tests
```

## Data collection (Part 02)

`src/heatwave_ml/ingestion/` has one adapter per source (IMD, NASA POWER, Open-Meteo forecast, synthetic). They land data in an immutable raw zone under `data/raw/`, and every run is logged.

```sh
uv run heatwave-ingest --help
uv run heatwave-ingest status
```

- Contract and operations: [`docs/data/raw-landing-zone.md`](../docs/data/raw-landing-zone.md)
- Field gaps Part 03 must handle: [`docs/data/field-availability.md`](../docs/data/field-availability.md)
- Why these sources: [`docs/decisions/0002-data-sources.md`](../docs/decisions/0002-data-sources.md)

## Preprocessing and feature engineering (Part 03)

`src/heatwave_ml/features/` is the feature logic **shared with the backend**: the labelling rule, seasonal normals, `build_features`, and the fitted preprocessor. `src/heatwave_ml/preprocessing/` is training-only: the synthetic generator, cleaning and the split.

```sh
uv run heatwave-prepare all     # → config/seasonal_normals.csv, data/heatwave_dataset.csv, ...
```

- Label rule: [`docs/data/heatwave-labeling-spec.md`](../docs/data/heatwave-labeling-spec.md)
- Synthetic data: [`docs/data/synthetic-dataset.md`](../docs/data/synthetic-dataset.md)
- Cleaning, features, parity, split, handoff to Part 04: [`docs/data/preprocessing.md`](../docs/data/preprocessing.md)

## Model training (Part 04)

`src/heatwave_ml/training/` trains, tunes (stratified CV on the train split only) and packages Logistic Regression, Random Forest and XGBoost. `src/heatwave_ml/bundle.py` is the artifact format **shared with evaluation and the backend**: load models with `ModelBundle.load`, never with a bare `joblib.load`.

```sh
uv run heatwave-train run       # → artifacts/runs/<run_id>/<model>/{model.joblib,bundle.json}
uv run heatwave-train summary   # comparison table from artifacts/experiment_log.jsonl
uv run heatwave-train verify    # re-check every bundle of the latest run
```

- Pipeline, search spaces, imbalance strategy, bundle contract, results, handoff to Part 05: [`docs/ml/training.md`](../docs/ml/training.md)
- Why: [`docs/decisions/0003-model-training-and-artifacts.md`](../docs/decisions/0003-model-training-and-artifacts.md)

## Evaluation, selection and the model registry (Part 05)

`src/heatwave_ml/evaluation/` scores a training run's bundles on the held-out test split, once. It applies the selection policy in `config/model_selection.yaml`, which must be committed before the run, and writes a report. `src/heatwave_ml/registry.py` is the production pointer **shared with the backend**: load the served model with `ModelRegistry.load_production()`.

```sh
uv run heatwave-evaluate run      # → registry/evaluations/<id>/{report.json,report.md}
uv run heatwave-evaluate verify   # re-derive the report from bundles + dataset
uv run heatwave-registry promote --evaluation <id>   # → registry/production.json
uv run heatwave-registry status
```

- Criteria, results, comparison table, justification, retraining and rollback, handoff to Part 06: [`docs/ml/evaluation.md`](../docs/ml/evaluation.md)
- Why: [`docs/decisions/0004-model-selection-and-registry.md`](../docs/decisions/0004-model-selection-and-registry.md)
