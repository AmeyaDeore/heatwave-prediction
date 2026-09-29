# Preprocessing and feature engineering (Part 03)

From raw landed data to the modelling dataset `data/heatwave_dataset.csv`. Related specs:

- [heatwave-labeling-spec.md](heatwave-labeling-spec.md): the target rule
- [synthetic-dataset.md](synthetic-dataset.md): the generator
- [field-availability.md](field-availability.md): the Part 02 gaps this part resolves

```sh
uv run heatwave-prepare all        # normals → dataset → observed → sample
```

| Step | Output | Committed? |
|---|---|---|
| `normals` | `config/seasonal_normals.csv`: 5 regions × 366 days | yes, needed at inference |
| `dataset` | `data/heatwave_dataset.csv` + `.manifest.json` | yes, the brief-named artifact (~375 KB) |
| `observed` | `data/processed/observed_dataset.parquet` + `.summary.json` | no (rebuild from `data/raw/`) |
| `sample` | `data/sample/forecast_features.csv` | yes, for backend/frontend development |

## 1. Code layout: what is shared and what is training-only

```
heatwave_ml/features/          ← SHARED: imported by training (Part 04) AND the backend (Part 07)
  schema.py       FEATURE_COLUMNS (fixed order), display labels, units, target name
  criteria.py     RiskCriteria (from config), classify(), temperature_deviation()
  normals.py      SeasonalNormals: derive / save / load / lookup
  engineering.py  build_features(): raw-shaped rows → model features, any source
  preprocessor.py preprocessor_for(model_family): seasonal imputer (+ scaler for LR)

heatwave_ml/preprocessing/     ← training-only
  synthetic.py    SyntheticGeneratorV1
  cleaning.py     clean(): stateless row-level cleaning with a counted report
  split.py        stratified train / validation / test
  dataset.py      build + write + load_modeling_dataset()
  cli.py          heatwave-prepare
```

## 2. Feature set

Fixed order, as `heatwave_ml.features.FEATURE_COLUMNS`:

| # | Column | Brief name | Unit | Source (training / inference) |
|---|---|---|---|---|
| 1 | `tmax_c` | Maximum Temperature | °C | synthetic (IMD-like) / Open-Meteo forecast |
| 2 | `normal_tmax_c` | Seasonal Normal Temperature | °C | `config/seasonal_normals.csv` / same table |
| 3 | `rh_pct` | Relative Humidity | % (daily mean, 2 m) | synthetic / forecast |
| 4 | `wind_ms` | Wind Speed | m/s **at 2 m** | synthetic (2 m) / forecast (10 m → 2 m) |
| 5 | `solar_mj_m2` | Solar Radiation | MJ/m²/day | synthetic / forecast |
| 6 | `precip_mm` | Precipitation | mm/day | synthetic / forecast |
| 7 | `temp_deviation_c` | **Temperature Deviation** (engineered) | °C | `round(tmax_c − normal_tmax_c, 2)` |

"Forecast Weather Data" (the brief's 7th input) is not a separate column. It is the **source** of features 1 and 3–6 at inference time (§5).

Carried alongside, but **not** features:

- `record_id`, `region_id` and `date` identify the row.
- `month` feeds only the seasonal imputer.
- `split` names the row's split.

## 3. Cleaning decisions, per feature

Cleaning (`preprocessing/cleaning.py`) is **stateless**: it learns nothing from the data. That is why running it on the whole dataset before the split cannot leak. Anything that learns a statistic is a fitted step (§4). Order: types → invalid values → duplicates → rows without Tmax.

| Feature | Out of bounds (`PLAUSIBLE_BOUNDS`, shared with Part 02's checks) | Missing | Why |
|---|---|---|---|
| `tmax_c` | outside −10–55 °C → missing, never capped | **row dropped** | The label and the engineered feature both depend on it. Imputing it would invent the target signal, and capping would turn a sentinel (99.9) into a plausible 55 °C. |
| `normal_tmax_c` | n/a | never missing | Always looked up from the normals table; any input value is overwritten, so a row's normal can't depend on its source. |
| `temp_deviation_c` | n/a | never missing | Recomputed from the two above. |
| `rh_pct` | 100–105 % → **capped** to 100 (sensor saturation in fog or rain); beyond → missing | **same-month training median** | Strongly seasonal (44 % in Mar vs 90 % in Aug), so an overall median would pull monsoon rows toward winter values. |
| `wind_ms` | −0.5–0 → **capped** to 0 (calibration offset near calm); beyond or > 60 → missing | **same-month training median** | Seasonal (1.8 m/s in Oct vs 4.0 in Jul). Values are converted to 2 m first (§5). |
| `solar_mj_m2` | −0.5–0 → capped to 0; beyond or > 45 → missing | **same-month training median** | Seasonal (13.8 in Jul vs 25 in Apr, monsoon cloud). |
| `precip_mm` | −0.5–0 → capped to 0; beyond (e.g. the −999 sentinel) or > 1000 → missing | **same-month training median** | Zero-inflated and skewed: a median (0 in dry months) rather than a mean, which one storm would inflate. |

**Considered and rejected: forward-fill.** Synthetic rows are independent samples with no day-to-day sequence, and the real series (IMD, NASA POWER) landed with 0 nulls. Forward-fill would help only real, time-adjacent gaps, and there are none.

**Duplicates:** de-duplicated on `region_id + date`, keeping the first copy. The report also counts how many repeats *disagreed* (6 of 20 in the current dataset), which is the case where "which copy is right?" matters.

**Units:** every source already reports the canonical units (raw-landing-zone.md). The one real mismatch is **wind height**: NASA POWER is at 2 m, Open-Meteo at 10 m. `build_features` converts to 2 m with the FAO-56 log profile, u₂ = u_z · 4.87 / ln(67.8·z − 5.42), which is × 0.748 from 10 m. It refuses rows whose height is unknown. `check_units` fails loudly on a Kelvin/Fahrenheit Tmax or a 0–1 humidity fraction from a future source. Values are rounded to 0.01 so float32 IMD values don't carry `39.52000045776367`-style noise.

**Logged counts** (seed 42, from the manifest's `cleaning` section):

| Step | Rows |
|---|---|
| Generated | 5,000 |
| Tmax out of bounds → missing | 5 |
| RH capped at 100 / RH out of bounds → missing | 5 / 4 |
| Wind capped at 0 / out of bounds → missing | 7 / 1 |
| Solar capped at 0 / out of bounds → missing | 6 / 2 |
| Precip capped at 0 / out of bounds → missing | 9 / 4 |
| Duplicate region+date dropped (of which disagreed) | 20 (6) |
| Dropped: Tmax missing (incl. the 5 invalid) | 12 |
| **Kept** | **4,968** |
| Left missing for the fitted imputer: RH / wind / solar / precip | 102 / 84 / 97 / 107 |

## 4. Fitted preprocessing, scaling and leakage

`preprocessor_for(model_family)` returns an **unfitted** sklearn `Pipeline`:

- `impute`: `SeasonalMedianImputer`, which learns per-month medians. It raises if Tmax, the normal or the deviation is missing.
- `scale`: `StandardScaler` for `logistic_regression`, or `"passthrough"` for `random_forest` and `xgboost`.

| Model | Scaling | Why |
|---|---|---|
| Logistic Regression | yes | Gradient-based with an L2 penalty: unscaled features (precip 0–190 vs deviation −5–10) distort both convergence and the penalty. |
| Random Forest | no | Threshold splits are invariant to monotone rescaling. |
| XGBoost | no | Same. |

**Leakage guard.** Nothing in Part 03 fits these steps. Part 04 must put the preprocessor *inside* each model `Pipeline` and fit it on training rows only (inside each CV fold during tuning). The fitted pipeline is what gets packaged and served, so validation, test and live rows are transformed with training statistics. Tests assert this: extreme test values do not move the fitted medians, and the scaler's mean equals the training mean.

```python
from pathlib import Path

from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline

from heatwave_ml.features import model_input, preprocessor_for
from heatwave_ml.preprocessing.dataset import load_modeling_dataset

splits = load_modeling_dataset(Path("data/heatwave_dataset.csv"))
train = splits["train"]
model = Pipeline([("pre", preprocessor_for("random_forest")), ("clf", RandomForestClassifier())])
model.fit(model_input(train), train["risk_class"])  # model_input = 7 features + month
```

## 5. Train-time vs inference-time parity

**One implementation.** `build_features(frame, normals)` is the only code that turns weather into features. It takes raw-landing-shaped rows (`region_id, date, tmax_c, rh_pct, wind_ms, wind_height_m, solar_mj_m2, precip_mm`) from **any** source:

- **Training:** synthetic rows, via `prepare_modeling_dataset`.
- **Real reference set:** IMD + NASA POWER history, via `build_observed_dataset`.
- **Inference (Part 07):** Open-Meteo forecast rows. `build_forecast_sample` already runs this path, and its output is committed as `data/sample/forecast_features.csv`.

Part 07 must `from heatwave_ml.features import build_features, model_input` and then call the packaged model pipeline. It must **not** reimplement any of it. A test feeds the same weather through the "training shape" (2 m wind, with a stale normal attached) and the "forecast shape" (10 m wind, no normal), and asserts identical features.

**Forecast vs observed substitution.** Training rows describe the *observed* conditions on the day. At inference, the same columns hold the *forecast* for the target day (lead 1–3 days). No lagged or "yesterday" features exist, so a forecast row and an observed row have exactly the same shape and meaning. The model learns "weather like this → class", and inference asks "if the forecast weather happens, which class?" What differs is error, not definition:

| Residual difference | Size | Owner |
|---|---|---|
| Forecast error grows with `lead_days` | unmeasured | Part 05: evaluate by lead time once forecasts are archived; Part 07/12 surface `lead_days` with each prediction |
| Open-Meteo Tmax vs IMD-cell normal (different grids and sources; field-availability §2.2 measured NASA−IMD at +1.33 °C) | unmeasured for Open-Meteo | Part 05: compare archived forecasts with IMD; if biased, add a per-source offset **inside `build_features`**, so training and serving still share it |
| Open-Meteo resolves sub-city differences (Colaba ~3 °C cooler); the training normals do not | known | region stays a non-feature; Part 05 distribution-shift check |

Missing values at inference: RH, wind, solar and precip are imputed by the packaged imputer using *training* medians. A missing forecast Tmax is rejected (the imputer raises), and Part 07 should return an error for that region rather than a prediction.

## 6. Split

- Stratified on `risk_class`, seed **42** (`RANDOM_SEED`), using sklearn `train_test_split` twice.
- **70 / 15 / 15** train / validation / test (`TEST_FRACTION`, `VALIDATION_FRACTION`).
- *Validation* is for Part 04's tuning decisions. *Test* stays untouched until Part 05's final evaluation.

| Split | Rows | NORMAL | HEATWAVE | SEVERE_HEATWAVE |
|---|---|---|---|---|
| train | 3,476 | 2,814 (80.96 %) | 365 (10.50 %) | 297 (8.54 %) |
| validation | 746 | 604 (80.97 %) | 78 (10.46 %) | 64 (8.58 %) |
| test | 746 | 604 (80.97 %) | 78 (10.46 %) | 64 (8.58 %) |
| **all** | **4,968** | 4,022 (80.96 %) | 521 (10.49 %) | 425 (8.55 %) |

The class imbalance (roughly 81 / 10 / 9) is expected and intended. Part 04 should use class weighting or train-only resampling, and Part 05 should lead with per-class precision and recall and macro-F1, not accuracy. Always-NORMAL scores 81 %.

## 7. Determinism

The same raw input and seed give a byte-identical `data/heatwave_dataset.csv`: SHA-256 `7412ab78bc55f986aad532839b094c4e5b41165037d1c17e644d384aede09ecd`, reproduced by a plain rerun and by a forced re-generation (2026-09-28). Every run writes the manifest (`data/heatwave_dataset.manifest.json`). It records:

- the dataset hash and the normals hash,
- the generator version, seed and landed file,
- the rule version and the class-index mapping,
- the split seed and fractions, with per-split class counts,
- the missing values left for the imputer, per split,
- the full cleaning report,
- the label-vs-rule agreement.

## 8. Handoff note (Part 03 → Part 04)

> Final modelling dataset at: `data/heatwave_dataset.csv` (manifest: `data/heatwave_dataset.manifest.json`; load with `heatwave_ml.preprocessing.dataset.load_modeling_dataset`). Row count: 4,968 (from 5,000 generated). Class distribution: NORMAL 4,022 / HEATWAVE 521 / SEVERE_HEATWAVE 425 (80.96 / 10.49 / 8.55 %); train 3,476, validation 746, test 746, stratified. Feature list: `tmax_c, normal_tmax_c, rh_pct, wind_ms, solar_mj_m2, precip_mm, temp_deviation_c` (in `FEATURE_COLUMNS` order; `month` is an imputer input, not a feature). Class index: NORMAL 0, HEATWAVE 1, SEVERE_HEATWAVE 2 (`RiskCriteria.class_to_index`). Label rule: `IMD-HW-DAILY-v1`. Shared feature-computation module at: `ml/src/heatwave_ml/features/` (`build_features`, `model_input`, `preprocessor_for`). Part 07 must import this, not reimplement it; it also needs `config/seasonal_normals.csv`. Train/test split seed: 42. Notes for Part 04/05: missing RH/wind/solar/precip are left in the splits for the in-pipeline imputer; the label noise ceiling is about 96 % rule agreement; use `data/processed/observed_dataset.parquet` (real 2000–2024 history, 1 heatwave date) as a false-alarm check.
