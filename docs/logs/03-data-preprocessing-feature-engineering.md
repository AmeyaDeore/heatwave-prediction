# Log 03 — Data preprocessing and feature engineering

| | |
|---|---|
| Plan | [Implementation/03-data-preprocessing-feature-engineering.md](../../Implementation/03-data-preprocessing-feature-engineering.md) |
| Status | Complete |
| Date | 2026-09-28 (built) · committed 2026-09-29 |
| Branch / commits | `main` · `44d0ca5` feat(preprocessing): implement feature engineering and modelling dataset |
| Tests | 42 new (`test_features.py`, `test_preprocessing.py`), 67 total |

## Summary

Defined the heatwave labelling rule as a versioned spec, built a reproducible IMD-calibrated synthetic generator (5,000 records), cleaning with counted outcomes, the engineered features, a fitted preprocessor shared by training and inference, and a stratified 70/15/15 split. The output is the modelling dataset Part 04 trains on, plus a real-history reference set.

## What was built

**Shared with the backend** — `ml/src/heatwave_ml/features/` (Part 07 must import this, never reimplement it):

| Module | Contents |
|---|---|
| `criteria.py` | `RiskCriteria` (loads `config/risk_classes.yaml`) and `classify()`: the one implementation of the label rule |
| `normals.py` | `SeasonalNormals`: IMD 1991–2020 normal per region and day (±15-day smoothing) |
| `engineering.py` | `build_features()`, `temperature_deviation()`, `model_input()`; wind 10 m → 2 m conversion (FAO-56) |
| `preprocessor.py` | `preprocessor_for(family)`: `SeasonalMedianImputer` (per-month train medians for RH, wind, solar, precip; raises if Tmax/normal/deviation missing) + `StandardScaler` for LR only, `"passthrough"` for trees |
| `schema.py` | `FEATURE_COLUMNS`, `FEATURE_LABELS` (human-readable names for Part 06/UI), units, `MONTH_COLUMN`, `TARGET_COLUMN` |

**Training-only** — `ml/src/heatwave_ml/preprocessing/`: `synthetic.py` (`SyntheticGeneratorV1`, `imd-sim-v1`), `cleaning.py`, `split.py`, `dataset.py` (build, manifest, `load_modeling_dataset()`), `cli.py` (`heatwave-prepare normals / dataset / observed / sample / all`).

**Outputs**

| File | What |
|---|---|
| `data/heatwave_dataset.csv` + `.manifest.json` | 4,968 rows (from 5,000), SHA-256 `7412ab78…09ecd`; manifest records cleaning counts, split, class distribution, rule version, feature labels/units |
| `config/seasonal_normals.csv` | IMD 1991–2020 normals, also needed at inference |
| `data/processed/observed_dataset.parquet` | Real IMD + NASA POWER 2000–2024 history, same rule; contains **one** heatwave date — a false-alarm check |
| `data/sample/forecast_features.csv` | Forecast rows run through the inference feature path |

**Docs:** `docs/data/heatwave-labeling-spec.md`, `docs/data/synthetic-dataset.md`, `docs/data/preprocessing.md`.

## Key decisions and why

- **Label rule `IMD-HW-DAILY-v1`:** departure D = Tmax − normal; D ≥ 6.5 → SEVERE, 4.5 ≤ D < 6.5 → HEATWAVE, only if Tmax reaches the zone minimum (coastal 37 °C, plains 40, hills 30); absolute Tmax ≥ 47 → SEVERE, ≥ 45 → HEATWAVE; take the worse. Thresholds read from config, never hard-coded. Duration, spatial extent, humidity and warm nights are deliberately out of v1 (duration belongs to alerting, Parts 09/13).
- **Synthetic data, heat events enriched:** real Mumbai history has one heatwave date in 25 years, so a model would never see minority classes. The generator draws calibrated anomalies (pre-monsoon events most likely), 10 % borderline rows near thresholds, climatology-based RH/solar/wind/precip that respond to heat, and realistic defects (missing values, out-of-bounds, sentinels, duplicates).
- **Labels from true Tmax, features from observed Tmax (+0.3 °C noise):** gives an honest ~96 % noise ceiling instead of a perfectly separable toy problem.
- **Tmax capped at 44 °C:** keeps a coastal city credible; the absolute 45/47 °C branch is covered by unit tests instead.
- **Region is not a feature:** sub-city regions are indistinguishable in real data.
- **Imputation is fitted, not done in Part 03:** it lives inside each model's pipeline, fit on train only (leakage guard).
- **Cleaning:** types → invalid (cap small overshoots, set gross errors to missing) → de-duplicate on region+date → drop rows with missing Tmax; every action counted in the manifest.

## Verification

- Rerun and forced re-generation reproduce the dataset byte for byte (SHA-256 `7412ab78…09ecd`).
- Rule agreement on observed features: **95.99 %**; all 199 disagreements lie within 1.02 °C of a threshold; rows > 1.5 °C away agree 100 % (tested).
- 5 hand-checked deviation values and 12 hand-checked rule cases; wind conversion checked against FAO-56.
- Parity test: training-shaped and forecast-shaped rows produce identical features.
- Leakage tests: extreme test values don't move fitted medians; scaler mean equals the training mean.
- Smoke check: sklearn LR/RF pipelines fit and predict on the dataset.

## Deviations from the plan and issues found

- Added the real observed dataset (not required by the plan) as a false-alarm reference.
- `*.manifest.json` files (only SHA-256 hashes) were excluded from detect-secrets, which flagged them as high-entropy strings.

## Open items / follow-ups

- Forecast error vs lead time (1–3 days) is unmeasured; needs archived forecasts (Parts 05/07/12).
- Possible bias between Open-Meteo Tmax and IMD normals is unmeasured.
- Synthetic prevalence of heat events is far above real-world; synthetic precision is not real-world precision.

## Handoff

Dataset `data/heatwave_dataset.csv`: 4,968 rows, NORMAL 4,022 / HEATWAVE 521 / SEVERE 425 (80.96 / 10.49 / 8.55 %); train 3,476, validation 746, test 746, stratified, seed 42. Features: `tmax_c, normal_tmax_c, rh_pct, wind_ms, solar_mj_m2, precip_mm, temp_deviation_c` (+ `month` as an imputer input). Class index NORMAL 0, HEATWAVE 1, SEVERE_HEATWAVE 2.
