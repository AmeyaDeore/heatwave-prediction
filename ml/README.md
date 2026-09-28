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
