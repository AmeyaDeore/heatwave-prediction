# Part 03 — Data Preprocessing & Feature Engineering

**Depends on:** 02 (data collection pipeline)
**Feeds into:** 04 (model training)
**Owner persona:** ML/data engineer

> **Revision 2 (2026-10-20, examiner feedback):** the new Maharashtra places need seasonal normals, and a synthetic generator v2 that represents inland (plains-zone) heat. The labelling rule, feature list, cleaning and parity design are unchanged. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

## 1. Objective

Turn raw landed data (or the synthetic dataset) into a clean, modeling-ready dataset with a well-defined feature set and a well-defined target label, matching exactly the variables and target enumerated in the project brief.

## 2. Target variable definition

- **Name:** Heatwave Classification.
- **Classes:** `NORMAL`, `HEATWAVE`, `SEVERE_HEATWAVE` — exactly three classes, ordinal in severity.
- **Labeling rule:** must be derived from a documented, reproducible rule based on simulated IMD heatwave criteria (temperature deviation from seasonal normal, absolute temperature thresholds, and duration/humidity considerations if used). Write this rule down explicitly as a specification before generating or labeling any data — it is the single most important artifact in this part, because every downstream metric (Part 05) and every "why" explanation (Part 06) is only meaningful relative to this rule.
- **Class balance check:** determine and document the expected/actual distribution across the three classes in the dataset; note that heatwave and severe-heatwave events are naturally rarer than normal conditions, which affects evaluation strategy in Part 05 (precision/recall matter more than raw accuracy for the minority classes).

## 3. Input feature set (finalized list, matching the brief exactly)

1. Maximum Temperature
2. Seasonal Normal Temperature
3. Relative Humidity
4. Wind Speed
5. Solar Radiation
6. Precipitation
7. Forecast Weather Data (for the live-inference feature set specifically — see Section 6)

Plus one **engineered** feature explicitly called out in the results slide:

8. **Temperature Deviation** = Maximum Temperature − Seasonal Normal Temperature (this becomes one of the top explanatory factors later, so its computation must be exact and consistent between training and inference).

## 4. Synthetic dataset generation (if not using fully live data)

Since the project's working dataset is 5,000 synthetic records simulating IMD heatwave criteria, specify this generation process precisely so it is reproducible:

- **Volume:** 5,000 records (configurable, but this is the documented baseline).
- **Generation approach:** sample each input feature from a distribution realistic for the target region/season (e.g., max temperature sampled around plausible Mumbai summer ranges, humidity within plausible tropical-coastal ranges), rather than uniform random sampling, so the resulting dataset resembles real conditions.
- **Label assignment:** apply the heatwave-criteria rule from Section 2 to each generated row to derive its class — do not assign labels independently of the rule, or the model will learn an inconsistent mapping.
- **Injected realism:** deliberately include some missing values, some borderline/edge cases near the classification thresholds, and some noise, so the model and pipeline are exercised the same way they would be against real data.
- **Reproducibility:** fix and document a random seed so the exact same synthetic dataset can be regenerated later for debugging or extension.
- **Output:** a single flat file (the brief names `data/heatwave_dataset.csv`) with one row per record and one column per feature plus the label.

## 5. Cleaning steps (applied regardless of data source)

1. **Missing value handling** — decide a strategy per feature (impute with a reasonable statistic, flag-and-drop, or forward-fill for time-adjacent readings) and apply it consistently; document why each choice was made per feature rather than using one blanket strategy for everything.
2. **Outlier/invalid value handling** — apply physically plausible bounds per feature (e.g., humidity between 0–100%, non-negative wind speed/precipitation/solar radiation) and decide whether out-of-bounds rows are corrected, dropped, or capped.
3. **Duplicate removal** — de-duplicate on location + date.
4. **Type/unit normalization** — ensure every feature is in one consistent unit across all sources before merging (critical if IMD and NASA POWER report temperature or wind speed in different units).
5. **Feature scaling decision** — decide, per candidate model family, whether scaling is required (tree-based models like Random Forest/XGBoost generally don't need it; Logistic Regression does) and plan the scaling step so it is fit only on training data and then applied identically to validation/test/live data (never fit scaling on the full dataset including test data — that is a data leakage bug to explicitly guard against).

## 6. Train-time vs. inference-time feature parity

This is a common source of subtle bugs, so it gets its own section:
- The exact same feature computation logic (especially Temperature Deviation) must be used both when building the training dataset and when preparing a live request for prediction.
- "Forecast Weather Data" is available for inference but, for historical training rows, the equivalent is the actual recorded conditions for that day — document explicitly how this substitution is handled so the model isn't trained on a materially different feature distribution than what it sees at inference time.
- Plan for this by implementing the feature computation as one shared step referenced by both the training pipeline (Part 04) and the backend's live prediction path (Part 07), not as two separately-written implementations.

## 7. Train/test split strategy

- Stratified split by class label (to preserve the rare heatwave/severe-heatwave classes proportionally in both sets) rather than a naive random split.
- Document the split ratio (e.g., holding out a fixed percentage for testing) and the random seed used, for reproducibility.
- Consider a validation set (separate from the final test set) if hyperparameter tuning is planned in Part 04, so the test set stays untouched until final evaluation.

## 8. Non-functional requirements

- The entire preprocessing step must be deterministic given the same raw input and seed — reruns should produce identical output.
- Preprocessing logic must be packaged so it can be imported/reused by the inference path in Part 07, not copy-pasted.
- Every cleaning decision (Section 5) should be logged with counts (e.g., "N rows had missing humidity, imputed with method X") so data quality is auditable.

## 9. Acceptance criteria / "done"

- [x] Heatwave classification rule documented as an explicit, versioned specification. *(`docs/data/heatwave-labeling-spec.md`, version `IMD-HW-DAILY-v1`, recorded in `config/risk_classes.yaml` as `labeling_rule_version`. Implemented once in `heatwave_ml.features.criteria.classify`; thresholds are read from config, never hard-coded.)*
- [x] Synthetic dataset generation script/process defined and reproducible with a fixed seed, producing the documented 5,000-record baseline (or the agreed volume). *(`SyntheticGeneratorV1` (`imd-sim-v1`), seed 42, 5,000 records, calibrated on real IMD and NASA POWER climatology; spec in `docs/data/synthetic-dataset.md`. Landed through Part 02's adapter. A rerun and a forced re-generation both reproduce the dataset byte for byte, SHA-256 `7412ab78…09ecd`.)*
- [x] All cleaning steps implemented with logged counts. *(`preprocessing/cleaning.py`: types → invalid (cap vs missing, per feature) → duplicates on region+date → Tmax-missing drop. Every action is counted in the manifest's `cleaning` section. Per-feature rationale in `docs/data/preprocessing.md` §3. Missing-value imputation is a *fitted* step (seasonal median, train-only) in `features/preprocessor.py`.)*
- [x] Temperature Deviation and any other engineered features computed and verified against a few hand-checked examples. *(`temperature_deviation()`: 5 hand-checked values including float32/float-rounding edges, plus 12 hand-checked rule cases in `ml/tests/test_features.py`. The wind 10 m → 2 m conversion is checked against FAO-56.)*
- [x] Feature computation logic packaged for reuse between training and inference. *(`heatwave_ml.features`: `build_features`, `model_input`, `preprocessor_for`, `SeasonalNormals`. A parity test asserts that training-shaped and forecast-shaped rows give identical features. The committed `data/sample/forecast_features.csv` is produced by the inference path.)*
- [x] Stratified train/test split produced and class distribution per split documented. *(70/15/15 train/validation/test, stratified, seed 42. Per-split counts are in the manifest and in `docs/data/preprocessing.md` §6: train 3,476, validation 746, test 746, each about 81/10.5/8.6 %.)*
- [x] Final dataset file produced at the agreed path and schema, ready for Part 04. *(`data/heatwave_dataset.csv`, the brief's path, with `data/heatwave_dataset.manifest.json`. Load it with `load_modeling_dataset()`. Smoke-checked end to end: sklearn Pipelines (LR/RF) fit and predict on it.)*

**Also produced:** `config/seasonal_normals.csv` (IMD 1991–2020, needed at inference). `data/processed/observed_dataset.parquet`: real 2000–2024 history, labelled by the same rule, containing a single heatwave date (a false-alarm check for Part 05). 42 new tests in `ml/tests/test_features.py` and `test_preprocessing.py` (67 in the whole repository, all passing).

## 10. Handoff note template

> Final modeling dataset at: <path>. Row count: <N>. Class distribution: <breakdown>. Feature list: <final columns>. Shared feature-computation module at: <path> (Part 07 must import this, not reimplement it). Train/test split seed: <value>.

**Filled in:** see §8 of [`docs/data/preprocessing.md`](../docs/data/preprocessing.md).

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **In progress.** ✅ R2.1 normals built (step 3, uncommitted). ✅ v1 training scope pinned (`config/training_scope.yaml`; v1 dataset verified byte-identical). ⏳ The observed-history export for Node (step 9) and generator v2 (step 10) are not started. The observed dataset itself is already rebuilt for all 18 places.

**Why:** the dataset and model only know five coastal Mumbai areas. Region is not a model feature, so the model *can* score a new place, but only from that place's seasonal normal (`normal_tmax_c`, `temp_deviation_c`). It is also trained on data that never shows inland conditions. Generator v1 draws humidity, wind, solar and rain from **Mumbai's** NASA POWER climatology and caps Tmax at **44 °C**, so the plains-zone thresholds (Tmax ≥ 40 °C, and Criterion B at ≥ 45/47 °C) never occur in training. A map that colours Nagpur or Chandrapur in May would then rest on extrapolation. Revision 2 fixes the data, not the method.

### R2.1 Seasonal normals for every place
- Extend `config/seasonal_normals.csv` with the existing `heatwave-prepare normals` method (IMD 1991–2020, ±15-day smoothing) for every place in Part 02 R2. **The five existing places' rows must stay byte-identical; a test asserts it.** That is what keeps the current production model, its explainer and the v1 dataset valid: neither the bundle nor the explainer pins the normals file's hash, and the dataset build checks normals per row, by value (`preprocessing/dataset.py`). If a full re-derivation on a re-pulled IMD history would change those rows by even 0.01 °C, the new places are appended instead and the existing rows kept as committed.
- The labelling rule `IMD-HW-DAILY-v1` already handles the plains zone (`min_tmax` 40 °C) and Criterion B, so **the rule version does not change**.

### R2.2 Synthetic generator v2 (`imd-sim-v2`)
A new generator version beside v1. v1 stays reproducible, and its dataset hash `7412ab78…` remains the record of the current production model.
- **Slots:** (place, date) pairs drawn across all places. Per-place weighting keeps the five Mumbai areas from being swamped, and the inland places are represented enough for per-zone evaluation (Part 05 R2).
- **Per-place climatology:** humidity, wind, solar and rain are drawn from each place's own NASA POWER 2000–2024 monthly mean/std (landed in Part 02 R2), instead of Mumbai's. The heat-response directions (drier, sunnier, calmer, less rain during heat) stay as in v1 §5 and are re-checked against inland history.
- **Tmax cap** raised from 44 °C to a physically plausible inland maximum (about 48 °C, set from the landed history's observed maxima), so Criterion B appears in training.
- **Volume:** the 5,000-record baseline is kept as the documented default. A larger count is a config value if per-zone class counts are too small, and the decision is recorded with its counts.
- **Unchanged:** labels from `classify()` (never drawn independently), seeded reproducibility, injected missing values, borderline cases, duplicates, and landing through Part 02's synthetic adapter.

### R2.3 Dataset build
- `data/heatwave_dataset.csv` is rebuilt from v2 with a new manifest (new SHA-256, generator `imd-sim-v2`, the normals hash, per-zone and per-place class counts).
- Split: stratified by class **and zone**, seed 42, so coastal and plains are both present in every split.
- `data/processed/observed_dataset.parquet` (the real-history false-alarm set) is extended to the new places, which gives Part 05 a real inland check.
- **Observed-history export for analysis (Part 14 R2):** the same observed set, IMD Tmax 1991–2024 per place, with normal, departure and the `IMD-HW-DAILY-v1` class, plus the NASA POWER context variables, is written as a versioned export file that the Node API imports into MongoDB. **The labelling rule runs only in Python** (`criteria.classify`). Node never re-implements it, the same principle as for predictions. The export records the rule version, the normals hash and which IMD cell each place uses.
- The committed `data/sample/forecast_features.csv` is regenerated for every place through the inference path (parity unchanged).

### R2.4 What does not change
The seven features and their order (`FEATURE_COLUMNS`), the Temperature Deviation computation, the cleaning steps, the train-only imputation, and the shared feature module the ML service imports (§6). Region is still not a feature.

### R2 acceptance criteria
- [x] `config/seasonal_normals.csv` covers every place in `config/regions.yaml`, and the original five are byte-identical to before. *(2026-10-20: built by `heatwave-prepare normals` from the IMD 1991–2020 pull: 18 places × 366 days, 0 nulls; the five original places' 1,830 rows are byte-identical and in the same order (`git diff`: 4,758 insertions, 0 deletions). `test_committed_normals_cover_every_configured_region` passes. Range per place: coastal peaks 34.7–36.3 °C, Vidarbha/Marathwada peaks 40.8–42.5 °C. **Also found and fixed:** generator v1 samples every region it is given, so with 18 monitored places a fresh `heatwave-prepare dataset` would have produced a different "v1". v1's scope is now pinned in `config/training_scope.yaml` and verified: the rebuild gives SHA-256 `7412ab78…`, identical.)*
- [ ] `imd-sim-v2` specified in `docs/data/synthetic-dataset.md` (per-place climatology, cap, slot weighting) and reproducible with a fixed seed. v1 is still reproducible.
- [ ] v2 dataset built with a manifest that records per-zone and per-place class distributions; plains rows include all three classes, Criterion B cases included.
- [ ] Split stratified by class and zone; counts documented in `docs/data/preprocessing.md`.
- [ ] Parity test still passes for training-shaped and forecast-shaped rows of a new inland place.
- [ ] Observed-history export produced for every place (1991–2024, labelled in Python, with rule version, normals hash and IMD cell), ready for the Part 14 R2 import. *(Partly: `heatwave-prepare observed` already rebuilds the labelled observed set for all 18 places (2000–2024, 164,376 rows, 265 HEATWAVE + 5 SEVERE days). The export file with the full 1991–2024 IMD span, rule version, normals hash and IMD cell is step 9.)*
