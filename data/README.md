# data/

| Directory | Committed? | Contents |
|-----------|-----------|----------|
| `raw/` | No | Immutable landed data from IMD, NASA POWER, Open-Meteo and the synthetic generator, plus `_meta/ingestion_log.jsonl` (Part 02). Recreate it with `uv run heatwave-ingest`. Layout: [`docs/data/raw-landing-zone.md`](../docs/data/raw-landing-zone.md). |
| `heatwave_dataset.csv` (+ `.manifest.json`) | **Yes** | The modelling dataset: 4,968 labelled, cleaned rows with a `split` column (Part 03). Rebuild with `uv run heatwave-prepare dataset`; the rebuild is byte-identical. See [`docs/data/preprocessing.md`](../docs/data/preprocessing.md). |
| `processed/` | No | Other Part 03 outputs, e.g. `observed_dataset.parquet` (real 2000–2024 history, labelled; Part 05's false-alarm check). |
| `sample/` | **Yes** | A small reference dataset (under 1 MB). Backend and frontend work can use it without running the ML pipeline. |
| `local/` | No | Local runtime state, e.g. the SQLite database `heatwave.db`. |

Collection scripts and exploration notebooks live under `ml/` (Parts 02–03). This directory holds data only.
