# Model training (Part 04)

This part takes the modelling dataset from Part 03 and produces three tuned, packaged candidate models: Logistic Regression, Random Forest and XGBoost. Part 05 evaluates them on the untouched test split and picks one. Related documents:

- [../data/preprocessing.md](../data/preprocessing.md): the dataset, features, fitted preprocessor and split (Part 03)
- [../decisions/0003-model-training-and-artifacts.md](../decisions/0003-model-training-and-artifacts.md): why the pipeline, imbalance strategy and bundle format are what they are

```sh
uv run heatwave-train run            # all three models, about 45 s on a 16-thread laptop
uv run heatwave-train summary        # comparison table from the experiment log (latest run)
uv run heatwave-train verify         # reload every bundle of the latest run and re-check it
uv run heatwave-train run --quick    # tiny searches: a smoke test in about 15 s
```

## 1. Code layout

```
heatwave_ml/bundle.py          ← SHARED: the artifact format. Parts 05, 06 and 07 load models with this
heatwave_ml/training/          ← training-only
  settings.py        TrainingSettings (CV_FOLDS, TRAINING_N_JOBS, MODEL_ARTIFACT_DIR, ...)
  models.py          ModelSpec per family: estimator, imbalance strategy, search space
  metrics.py         CV scorers (macro-F1 refit + per-class recall/F1 + log loss), validation report
  experiment_log.py  append-only JSONL log (Part 02's writer)
  trainer.py         load (without test) → baseline → ablation → tuning → final fit → package
  cli.py             heatwave-train
```

## 2. Pipeline stages (Part 04 §3)

| # | Stage | What happens |
|---|---|---|
| 1 | Load | `load_training_data` reads `data/heatwave_dataset.csv`. It checks the file's SHA-256 against its manifest, and checks that the rule version and class index match `config/risk_classes.yaml`. It keeps **train and validation only**: the test split is dropped here and never reaches the rest of the pipeline. |
| 2 | Per-model preprocessing | Every model is `Pipeline([("pre", preprocessor_for(family)), ("clf", estimator)])`. `pre` is Part 03's seasonal-median imputer, plus `StandardScaler` for Logistic Regression only, or `"passthrough"` for the tree models. |
| 3 | Baseline | Library-default hyperparameters with the chosen imbalance strategy, scored by k-fold CV. |
| 3b | Imbalance ablation | The same defaults **without** class weighting. This is the evidence for §4. |
| 4 | Tuning | Grid search (LR) or random search (RF, XGBoost) over the §3 spaces, with the same CV. Every candidate is logged. |
| 5 | Cross-validation | `StratifiedKFold(5, shuffle=True, random_state=42)` on the **train split only**. The preprocessor is inside the pipeline, so imputation medians and scaler statistics are learnt on each fold's training part. The held-out fold never contributes. The same fold assignment is used for every model and trial, so their scores are directly comparable. |
| 6 | Imbalance | Balanced class weighting for all three models, and no resampling (§4). |
| 7 | Final fit | The best candidate (highest mean CV macro-F1; ties go to the earliest candidate) is refit on the **full train split**. It is then scored on the validation split and packaged (§5). |

**Tuning objective: macro-F1.** It weighs each class equally, so it does not reward "always NORMAL" (81 % accuracy). Every trial also records accuracy, balanced accuracy, weighted F1, macro precision and recall, log loss, and per-class recall and F1. Part 05 can therefore re-rank by any of them (for example SEVERE_HEATWAVE recall) without retraining.

**Validation split.** Tuning uses only CV on train. The validation split is scored once per final model and recorded in the bundle, as an independent check that tuning didn't overfit the CV folds. It is not used to pick hyperparameters. Part 05 can use it for decisions such as calibration without touching test.

## 3. Hyperparameter search spaces

Sized for about 3,500 training rows. An exhaustive search isn't needed at this scale (Part 04 §3.4). Full spaces are in `training/models.py`, and each run's `run_started` log event records them.

| Model | Strategy | Space | Fixed |
|---|---|---|---|
| Logistic Regression | grid, 17 candidates | `C` ∈ 10⁻³ … 10⁵ (log-spaced, 2 per decade) | lbfgs (multinomial softmax), L2, `max_iter=5000` |
| Random Forest | random, 30 of 240 | `n_estimators` {200, 400, 600} · `max_depth` {None, 8, 12, 16, 24} · `min_samples_leaf` {1, 2, 4, 8} · `max_features` {sqrt, 0.5, 0.8, 1.0} | `random_state=42` |
| XGBoost | random, 40 | `learning_rate` log-U(0.01, 0.3) · `n_estimators` 100–800 · `max_depth` 2–8 · `min_child_weight` log-U(0.5, 16) · `subsample` U(0.6, 1) · `colsample_bytree` U(0.6, 1) · `reg_lambda` log-U(0.1, 10) | `multi:softprob`, `hist`, `random_state=42` |

Why a grid for LR: it has one knob. The grid runs to 10⁵ because CV macro-F1 plateaus from C ≈ 10³ onwards (0.8467 for every C from 10³ to 10⁷, checked on 2026-09-28). With only 7 features and 3,476 rows, the linear model gains from having almost no penalty. On a tie, sklearn's earliest (most regularised) candidate wins, so the choice is C = 1000, the start of the plateau, not its arbitrary far end.

## 4. Class imbalance strategy

| Model | Strategy | How |
|---|---|---|
| Logistic Regression | class weighting | `class_weight="balanced"` |
| Random Forest | class weighting | `class_weight="balanced"` |
| XGBoost | class weighting | balanced `sample_weight` passed to `fit()` (`XGBClassifier` has no `class_weight` for multiclass). sklearn slices it per CV fold. |

Balanced weights on train: NORMAL 0.41, HEATWAVE 3.17, SEVERE_HEATWAVE 3.90 (`n / (3 · n_class)`). Every bundle records them.

**No resampling.** Class weighting gives the same expected loss as random oversampling, without duplicated rows (which inflate CV scores when copies land in both fold halves) or synthetic rows. It is native to all three libraries, so no new dependency (`imbalanced-learn`) and no extra pipeline step at serving time. The test and validation splits are never reweighted or resampled.

**Evidence: the ablation** (5-fold CV on train, library defaults, 2026-09-28):

| Model | Weighting | macro-F1 | NORMAL recall | HEATWAVE recall | SEVERE recall |
|---|---|---|---|---|---|
| Logistic Regression | none | 0.8424 | 0.973 | 0.641 | 0.885 |
| | **balanced** | 0.8394 | 0.905 | **0.910** | **0.922** |
| Random Forest | none | **0.8859** | 0.979 | 0.792 | 0.879 |
| | **balanced** | 0.8774 | 0.954 | **0.871** | **0.916** |
| XGBoost | none | 0.8684 | 0.975 | 0.767 | 0.866 |
| | **balanced** | **0.8703** | 0.969 | **0.792** | **0.882** |

Weighting raises HEATWAVE and SEVERE_HEATWAVE recall for every model, by 1.6 to 27 points. It pays for this with NORMAL recall, that is, more false alarms. For Logistic Regression and Random Forest it slightly lowers macro-F1 (−0.003 and −0.009). The strategy is kept anyway: Part 05 §3 weights a missed severe event above a false alarm for an early-warning system, and the ablation shows the trade is large in the right direction and small in the wrong one. The unweighted numbers stay in the experiment log (`stage: imbalance_ablation`) if Part 05 wants to revisit this.

## 5. Artifact bundle contract (Part 04 §5)

One immutable directory per model per run:

```
ml/artifacts/
  experiment_log.jsonl                       append-only, every run (§6)
  runs/<run_id>/<family>/
    model.joblib                             the fitted Pipeline: pre (imputer → scaler | passthrough) → clf
    bundle.json                              the contract below
```

| §5 requirement | Where |
|---|---|
| The fitted model object | `model.joblib`: the whole sklearn `Pipeline`. Preprocessing is *inside* the model object, so serving can't apply a different transform. |
| Exact fitted preprocessing, or a no-op marker | Pickled in `pre`. `bundle.json → preprocessing.scale` is `"StandardScaler"` (LR) or `"passthrough"` (trees, the no-op marker), and `load` checks it against the pickled step. |
| Exact ordered feature names | `feature_columns` (the 7 features, in estimator order) and `input_columns` (+ `month`, for the imputer). `load` checks both against the pickled model's `feature_names_in_`. `predict_proba` selects columns **by name**, so a caller's column order can't permute features. A missing column raises `KeyError`. |
| Version id + training dataset hash | `model_version` = `<family>-<run_id>`, e.g. `random_forest-20260928T100821Z-0bde51`. `training_data.sha256` is the dataset's SHA-256 (it matches Part 03's manifest). Also `run_id`, `git.commit` and `labeling_rule_version`. |
| Class label mapping | `class_labels: {"0": "NORMAL", "1": "HEATWAVE", "2": "SEVERE_HEATWAVE"}`, stored with the model and checked against the estimator's `classes_`. `predict_proba` returns columns named by label. |

`bundle.json` also records the tuned `hyperparameters`, the full `estimator_params`, the `imbalance` strategy and weights, `tuning` (search, candidates, best trial, CV mean ± std per metric), the `validation` report (per-class P/R/F1, confusion matrix, log loss), `reproducibility.prediction_fingerprint`, `model_sha256` and `library_versions`.

**Loading** (Parts 05–07):

```python
from pathlib import Path

from heatwave_ml.bundle import ModelBundle
from heatwave_ml.features import build_features, model_input

bundle = ModelBundle.load(Path("ml/artifacts/runs/<run_id>/random_forest"))
features = model_input(build_features(rows, normals))
proba = bundle.predict_proba(features)  # columns NORMAL, HEATWAVE, SEVERE_HEATWAVE
```

`ModelBundle.load` raises `BundleError` in any of these cases:

- the model file's SHA-256 differs from `bundle.json`. This is checked **before** unpickling, so a swapped file is never executed.
- the installed scikit-learn or XGBoost version differs from training. Pickles aren't portable across versions; the shared `uv.lock` keeps backend and ml identical.
- the feature list, class mapping or preprocessing marker disagrees with the pickled model.
- the bundle schema is unknown.

`save_bundle` refuses to overwrite an existing bundle.

## 6. Experiment log

`ml/artifacts/experiment_log.jsonl` is written with the same append-only, fsync-per-line writer as the Part 02 ingestion log. Every line has `schema`, `logged_at`, `event` and `run_id`.

| `event` | Written | Key fields |
|---|---|---|
| `run_started` | once per run | `dataset` (path, sha256, rule version, split seed, row counts, `test_rows_used: 0`), `seed`, `cv`, `refit_metric`, `models` (search type, n_iter, **full search space**, imbalance strategy), `library_versions`, `git` |
| `trial` | once per CV evaluation | `stage` (`baseline` · `imbalance_ablation` · `tuning`), `model_family`, `search_params`, `estimator_params` (all of them), `imbalance_strategy`, `cv.metrics.<metric>.{mean, std, folds[]}`, `mean_fit_seconds`; tuning trials add `trial` and `rank` |
| `model_selected` | per model | `best_trial`, `best_params`, `selected_by`, `cv`, `baseline_f1_macro`, `tuning_seconds` |
| `model_packaged` | per model | `model_version`, `bundle`, `model_sha256`, `prediction_fingerprint`, `validation` |
| `run_finished` / `run_failed` | once | `status`, `duration_seconds`, `bundles` · or `error` |

A full run writes 101 events, including 93 trials (3 × 2 defaults plus 17 + 30 + 40 tuning candidates). `ExperimentLog(path).run(run_id)` groups a run's events for Part 05, and `heatwave-train summary --run <id>` prints them. The log is git-ignored with the bundles it describes; §7 reproduces its headline numbers.

## 7. Results: run `20260928T100821Z-0bde51`

Dataset `7412ab78…09ecd`, seed 42, 5-fold CV on the 3,476 training rows, 45.6 s end to end (tuning: LR 2.2 s, RF 19.3 s, XGBoost 14.8 s).

**Macro-F1, CV on train (mean ± std over 5 folds):**

| Model | Baseline | Tuned | Best hyperparameters |
|---|---|---|---|
| Logistic Regression | 0.8394 | 0.8467 ± 0.026 | `C=1000` |
| Random Forest | 0.8774 | 0.8791 ± 0.011 | `n_estimators=600, max_depth=24, min_samples_leaf=1, max_features=0.5` |
| XGBoost | 0.8703 | 0.8815 ± 0.012 | `n_estimators=114, max_depth=6, learning_rate=0.079, subsample=0.61, colsample_bytree=0.99, min_child_weight=0.81, reg_lambda=0.21` |

**Validation split (746 rows; the final models, fit on the full train split):**

| Model | Accuracy | macro-F1 | HEATWAVE P / R | SEVERE P / R | SEVERE → NORMAL | Log loss |
|---|---|---|---|---|---|---|
| Logistic Regression | 0.9330 | 0.8744 | 0.646 / 0.936 | 0.868 / 0.922 | 0 of 64 | 0.181 |
| Random Forest | 0.9651 | 0.9197 | 0.841 / 0.885 | 0.861 / 0.969 | 0 of 64 | 0.094 |
| XGBoost | 0.9651 | 0.9140 | 0.857 / 0.846 | 0.859 / 0.953 | 0 of 64 | 0.093 |

These are **not** the Part 05 results: the test split has not been scored. Things worth knowing before Part 05 reads them:

- **Tuning gains are small** (+0.002 RF, +0.011 XGBoost, +0.007 LR over defaults), and RF and XGBoost are within one CV standard deviation of each other. The dataset is close to its noise ceiling: the labelling rule applied to the *observed* (noisy) features agrees with the stored labels 96.0 % of the time (Part 03 manifest), and the tree models reach 94.3–94.6 % CV accuracy and 96.5 % on validation.
- **Validation scores are about 0.03–0.04 higher than CV** for all three models. The final models were fit on 25 % more rows than each CV fold model, and validation is a single 746-row sample: each of its 64 SEVERE rows is 1.6 points of SEVERE recall. Treat the CV means as the tuning signal and validation as a sanity check.
- **Logistic Regression is the floor, as intended.** The rule is a threshold on deviation *and* Tmax, which a linear boundary can only approximate. Its HEATWAVE precision (0.65) is where that shows.
- **Random Forest's bundle is 14 MB** (600 fully grown trees), against 0.7 MB for XGBoost and 3.5 KB for LR. That matters for Part 05's latency check, not for correctness.

## 8. Reproducibility and run time (Part 04 §6)

- **Seeded everywhere:** the CV folds, the random search's candidate draws, and each estimator's `random_state` all come from `RANDOM_SEED` (42). Each fit is single-threaded (`n_jobs=1` in the estimator), and parallelism only runs whole fits side by side (`TRAINING_N_JOBS`). So the degree of parallelism can't change a result.
- **Verified bit-for-bit (2026-09-28):** a second full run (`20260928T100930Z-56b49c`, in a separate directory, with `TRAINING_N_JOBS=4` instead of all cores) reproduced every model byte for byte. The chosen hyperparameters and all CV scores are identical, the `model.joblib` SHA-256 is identical for all three models, and so are the prediction fingerprints (the SHA-256 of float64 `predict_proba` on the validation split): LR `85f91701…`, RF `78feee9c…`, XGBoost `f8c2334b…`. `test_training_is_reproducible` asserts the same property on every test run.
- `heatwave-train verify` re-derives each bundle's fingerprint from the current dataset. It fails if the model file, dataset or libraries have drifted.
- **Time:** 45.6 s for all three models, on the budget in §6. The training pipeline has no dependency on the backend, and Part 07 only ever loads bundles.

## 9. Handoff note (Part 04 → Part 05)

> Three trained model artifacts available at `ml/artifacts/runs/20260928T100821Z-0bde51/{logistic_regression,random_forest,xgboost}/`, each following the Section 5 bundle contract (`model.joblib` + `bundle.json`; load with `heatwave_ml.bundle.ModelBundle.load`). Versions: `logistic_regression-20260928T100821Z-0bde51`, `random_forest-…`, `xgboost-…`. They are trained on dataset SHA-256 `7412ab78…09ecd` (rule `IMD-HW-DAILY-v1`). Experiment log at `ml/artifacts/experiment_log.jsonl` (`heatwave-train summary --run 20260928T100821Z-0bde51`). Best hyperparameters per model: LR `C=1000`; RF `n_estimators=600, max_depth=24, min_samples_leaf=1, max_features=0.5`; XGBoost `n_estimators=114, max_depth=6, learning_rate=0.079, subsample=0.61, colsample_bytree=0.99, min_child_weight=0.81, reg_lambda=0.21`. Tuning objective: 5-fold stratified CV macro-F1 on train. Class imbalance strategy used: balanced class weighting for all three (LR and RF via `class_weight`, XGBoost via `sample_weight`), no resampling; the unweighted ablation is in the log. The test split has not been read by any Part 04 code. Part 05 can now run final evaluation against the held-out test set.

**Also for Part 05:**

- Artifacts are git-ignored. On a fresh clone, `uv run heatwave-train run` rebuilds identical models (§8); the run id will differ, so the production pointer should record the model SHA-256 as well as the version.
- Calibration (Part 05 §2): log loss is 0.09 for the trees on validation, but class weighting deliberately shifts probabilities toward the rare classes. Check the reliability curves before exposing "confidence".
- Carried over from Part 03 (still open): how forecast error grows with lead time, and any bias between Open-Meteo Tmax and the IMD normals ([preprocessing.md §5](../data/preprocessing.md#5-train-time-vs-inference-time-parity)). The real-history false-alarm set is `data/processed/observed_dataset.parquet`.
