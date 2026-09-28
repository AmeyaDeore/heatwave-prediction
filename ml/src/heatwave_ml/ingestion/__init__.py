"""Part 02: data collection pipeline.

Source adapters (IMD, NASA POWER, Open-Meteo forecast, synthetic) fetch data and
land it, unchanged in meaning, in the immutable raw zone under ``RAW_DATA_DIR``.
Every run is recorded in the ingestion log. Cleaning belongs to Part 03.

Entry point: ``uv run heatwave-ingest --help``. Contract: ``docs/data/raw-landing-zone.md``.
"""
