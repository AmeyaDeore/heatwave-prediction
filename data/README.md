# data/

| Directory | Committed? | Contents |
|-----------|-----------|----------|
| `raw/` | No | Immutable landed data from IMD, NASA POWER, Open-Meteo and the synthetic generator, plus `_meta/ingestion_log.jsonl` (Part 02). Recreate it with `uv run heatwave-ingest`. Layout: [`docs/data/raw-landing-zone.md`](../docs/data/raw-landing-zone.md). |
| `processed/` | No | Cleaned, feature-engineered datasets (Part 03). |
| `sample/` | **Yes** | A small reference dataset (under 1 MB). Backend and frontend work can use it without running the ML pipeline. |
| `local/` | No | Local runtime state, e.g. the SQLite database `heatwave.db`. |

Collection scripts and exploration notebooks live under `ml/` (Parts 02–03). This directory holds data only.
