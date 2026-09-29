# Log 04 — Model development and training

| | |
|---|---|
| Plan | [Implementation/04-model-development-training.md](../../Implementation/04-model-development-training.md) |
| Status | Complete (re-verified at the start of Part 05 on 2026-09-29) |
| Date | 2026-09-28 (built) · committed 2026-09-29 |
| Branch / commits | `main` · `894364b` feat(training): implement model training pipeline and artifact bundles |
| Tests | 21 new (`ml/tests/test_training.py`), 88 total |

## Summary

Built a reproducible training pipeline that produces three tuned, packaged candidate models — Logistic Regression, Random Forest and XGBoost — from the Part 03 dataset, with an append-only experiment log and a verified artifact format shared by evaluation and serving. The test split is never read.

## What was built

| Path | Role |
|---|---|
| `ml/src/heatwave_ml/bundle.py` | **Shared** artifact format: `save_bundle`, `ModelBundle.load` (checks SHA-256 *before* unpickling, then library versions, feature order, class mapping, preprocessing marker), `predict_proba` by column name |
| `training/models.py` | `ModelSpec` per family: estimator, imbalance strategy, search space; `default_specs()`, `quick_specs()` |
| `training/trainer.py` | `load_training_data` (drops test at load) → baseline → imbalance ablation → tuning → final fit → validation report → package |
| `training/metrics.py` | CV scorers (macro-F1 refit + per-class recall/F1, log loss, …), `holdout_report` |
| `training/experiment_log.py` | Append-only JSONL log (reuses the Part 02 writer) |
| `training/cli.py` | `heatwave-train run [--models] [--quick] / summary / verify` |

**Artifacts** (git-ignored): `ml/artifacts/runs/20260928T100821Z-0bde51/{logistic_regression,random_forest,xgboost}/{model.joblib,bundle.json}` and `ml/artifacts/experiment_log.jsonl` (101 events, 93 CV trials).

**Docs:** `docs/ml/training.md`, ADR `docs/decisions/0003-model-training-and-artifacts.md`.

## Key decisions and why

- **Preprocessing inside each model's sklearn `Pipeline`** (`pre` → `clf`): fitted per CV fold, packaged with the model, so serving cannot apply a different transform.
- **Stratified 5-fold CV on the train split only** (seed 42); validation scored once per final model as a sanity check; test dropped at load time.
- **Tuning objective macro-F1** (accuracy rewards "always NORMAL" at 81 %); every trial also logs accuracy, balanced accuracy, weighted F1, macro P/R, log loss, per-class recall and F1.
- **Search spaces:** LR grid over 17 `C` values (10⁻³…10⁵); RF random search 30 of 240; XGBoost random search 40.
- **Imbalance: balanced class weighting for all three, no resampling** (`class_weight` for LR/RF, `sample_weight` for XGBoost). The ablation showed +1.6 to +27 points of heatwave-class recall for at most −0.009 macro-F1.
- **Bundle contract:** version id `<family>-<run_id>`, dataset SHA-256, ordered `feature_columns`/`input_columns`, class mapping, preprocessing marker, hyperparameters, imbalance weights, validation report, prediction fingerprint, library versions. Bundles are immutable.
- **Rejected:** SMOTE/oversampling, XGBoost native JSON (loses the preprocessor), ONNX, early stopping on validation, refitting on train+validation.

## Results (run `20260928T100821Z-0bde51`, 45.6 s end to end)

| Model | CV macro-F1 baseline → tuned | Best hyperparameters | Validation acc / macro-F1 |
|---|---|---|---|
| Logistic Regression | 0.8394 → 0.8467 | `C=1000` | 0.9330 / 0.8744 |
| Random Forest | 0.8774 → 0.8791 | 600 trees, depth 24, min leaf 1, max_features 0.5 | 0.9651 / 0.9197 |
| XGBoost | 0.8703 → 0.8815 | 114 rounds, depth 6, lr 0.079, subsample 0.61, colsample 0.99, min_child_weight 0.81, λ 0.21 | 0.9651 / 0.9140 |

0 of 64 validation SEVERE days predicted NORMAL for every model. RF bundle 14 MB vs XGBoost 0.7 MB vs LR 3.5 KB.

## Verification

- Bit-for-bit reproducible: a second full run with different parallelism (`TRAINING_N_JOBS=4`) produced identical `model.joblib` hashes and prediction fingerprints for all three models.
- `heatwave-train verify` re-checks hash, versions, features, classes and predictions — re-run on 2026-09-29 before Part 05: all `ok`, 88 tests passing.
- Tests poison every test-split row with a missing Tmax, which the imputer rejects, so any use of a test row would fail the run.

## Deviations from the plan and issues found

- Tuning gains are small (+0.002 to +0.011); the dataset is near its ~96 % noise ceiling.
- Validation scores are ~0.03–0.04 above CV (final models see 25 % more rows; validation is a single 746-row sample).

## Open items / follow-ups

- Class weighting shifts probabilities toward rare classes — calibration had to be checked in Part 05 (done: all ECE ≤ 0.05).
- Bundles are pinned to the locked scikit-learn/XGBoost versions; upgrading either means retraining.

## Handoff

Three bundles following the contract, loadable with `ModelBundle.load`; experiment log at `ml/artifacts/experiment_log.jsonl`. Part 05 evaluates them on the untouched test split.
