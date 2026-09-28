# Part 03 — Data Preprocessing & Feature Engineering

**Depends on:** 02 (data collection pipeline)
**Feeds into:** 04 (model training)
**Owner persona:** ML/data engineer

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

- [ ] Heatwave classification rule documented as an explicit, versioned specification.
- [ ] Synthetic dataset generation script/process defined and reproducible with a fixed seed, producing the documented 5,000-record baseline (or the agreed volume).
- [ ] All cleaning steps implemented with logged counts.
- [ ] Temperature Deviation and any other engineered features computed and verified against a few hand-checked examples.
- [ ] Feature computation logic packaged for reuse between training and inference.
- [ ] Stratified train/test split produced and class distribution per split documented.
- [ ] Final dataset file produced at the agreed path and schema, ready for Part 04.

## 10. Handoff note template

> Final modeling dataset at: <path>. Row count: <N>. Class distribution: <breakdown>. Feature list: <final columns>. Shared feature-computation module at: <path> (Part 07 must import this, not reimplement it). Train/test split seed: <value>.
