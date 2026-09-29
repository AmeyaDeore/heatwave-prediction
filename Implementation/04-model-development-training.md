# Part 04 — Model Development & Training Pipeline

**Depends on:** 03 (preprocessing/feature engineering)
**Feeds into:** 05 (evaluation/selection), 06 (SHAP)
**Owner persona:** ML engineer

## 1. Objective

Build a training pipeline that produces three trained candidate models — Logistic Regression, Random Forest, and XGBoost — against the finalized dataset from Part 03, in a way that is reproducible, comparable, and packageable for serving.

## 2. Why these three specific models (context for implementation choices)

- **Logistic Regression:** a linear baseline; fast, interpretable on its own (coefficients), useful as a sanity-check floor for the other models.
- **Random Forest:** an ensemble of decision trees; handles nonlinear relationships and feature interactions well, robust to unscaled features and outliers.
- **XGBoost:** a gradient-boosted tree ensemble; typically the strongest performer on structured/tabular data like this, at the cost of more hyperparameters to tune.

All three are also chosen because SHAP has well-supported, efficient explainer implementations for each (linear explainer for Logistic Regression, tree explainers for Random Forest and XGBoost) — this is why the model family choice in this part directly enables Part 06.

## 3. Training pipeline stages

1. **Load the finalized dataset** from Part 03's output path (train/test/validation already split).
2. **Per-model preprocessing branch** — apply feature scaling only for Logistic Regression; tree-based models consume unscaled features directly (per the decision in Part 03 Section 5).
3. **Baseline training run** — train all three models with reasonable default hyperparameters first, to get an initial comparison point before any tuning effort is spent.
4. **Hyperparameter tuning** — for each model, define the hyperparameter search space (e.g., regularization strength for Logistic Regression; tree depth, number of estimators, min samples per leaf for Random Forest; learning rate, number of boosting rounds, max depth, subsampling ratios for XGBoost) and a tuning strategy (grid search, random search, or a small number of manually reasoned trials, appropriate to the dataset size of ~5,000 records — an exhaustive search is unnecessary at this scale).
5. **Cross-validation** — use stratified k-fold cross-validation on the training set (not the held-out test set) during tuning, so the final test-set evaluation in Part 05 remains an honest, untouched estimate.
6. **Class imbalance handling** — given that Heatwave/Severe Heatwave are rarer than Normal (per Part 03 Section 2), explicitly decide and apply a strategy per model where supported: class weighting, or resampling of the training set only (never resample the test set). Document which strategy was used for which model.
7. **Final fit** — retrain each model with its selected best hyperparameters on the full training set.

## 4. Experiment tracking

- Every training run (baseline and each tuning trial) should record: model type, hyperparameters used, and the resulting cross-validation metrics, in a structured, append-only log — this doesn't need to be a heavyweight tool for a mini-project, but it must be more than "whatever was printed to the console and then lost."
- This log is what Part 05 draws on to justify the model selection decision, so it must be complete enough to reconstruct "why Random Forest was chosen" without re-running training.

## 5. Model artifact packaging

For each of the three trained models, define a single artifact bundle containing:
- The fitted model object itself.
- The exact fitted preprocessing/scaling step (for Logistic Regression) or a no-op marker (for tree models), so inference-time transformation is guaranteed identical to training-time.
- The exact ordered list of feature names the model expects, to guard against silent feature-order mismatches at inference time.
- A version identifier and the training dataset version/hash it was trained on, for traceability.
- The class label mapping (index-to-label, e.g., 0=Normal, 1=Heatwave, 2=Severe Heatwave) stored alongside the model, not assumed/hard-coded elsewhere.

## 6. Non-functional requirements

- Training must be reproducible: same dataset + same seed + same hyperparameters → same model, bit-for-bit where the algorithm allows (tree-based methods have some inherent nondeterminism to control via seeding).
- Total training time for all three models on ~5,000 records should be modest (well under the length of a coffee break) — if it isn't, something in the pipeline (e.g., an unnecessarily large hyperparameter search) needs to be scoped down.
- The training pipeline must be runnable independently of the backend service — Part 07 only ever consumes the packaged artifact, it never re-trains.

## 7. Acceptance criteria / "done"

- [x] Baseline versions of all three models trained and logged. *(`stage: baseline` trials in `ml/artifacts/experiment_log.jsonl`: library defaults + the chosen imbalance strategy, 5-fold CV macro-F1 LR 0.8394 / RF 0.8774 / XGBoost 0.8703. Also an `imbalance_ablation` trial per model with no weighting.)*
- [x] Hyperparameter search space defined and documented per model. *(`heatwave_ml.training.models.default_specs`: a 17-value C grid for LR, random search over 30 of 240 RF candidates and 40 XGBoost candidates. Documented in `docs/ml/training.md` §3, and written into every run's `run_started` log event.)*
- [x] Cross-validation implemented correctly (no leakage from test set into tuning). *(Stratified 5-fold on the train split only, seed 42. The imputer and scaler sit inside each model's Pipeline, so they are fit per fold. `load_training_data` drops the test split before anything else runs. The tests poison every test row with a missing Tmax, which the imputer rejects, so any use of a test row would fail the run.)*
- [x] Class imbalance strategy chosen and documented per model. *(Balanced class weighting for all three: `class_weight` for LR and RF, `sample_weight` for XGBoost. No resampling. The ablation evidence is in `docs/ml/training.md` §4: +1.6 to +27 points of heatwave-class recall, for at most −0.009 macro-F1. Each bundle records its strategy and weights.)*
- [x] Final fitted models produced and packaged per Section 5's artifact contract. *(`ml/artifacts/runs/20260928T100821Z-0bde51/<family>/{model.joblib,bundle.json}`, loaded with `heatwave_ml.bundle.ModelBundle.load`, which checks the hash, library versions, feature order, class mapping and preprocessing marker. `heatwave-train verify` passes. Retraining reproduced all three `model.joblib` files byte for byte.)*
- [x] Experiment log complete and shared with whoever owns Part 05. *(101 events, 93 CV trials, each with full params and per-fold scores. Schema in `docs/ml/training.md` §6, headline results in §7, and `heatwave-train summary` prints it. **Share `docs/ml/training.md` with the Part 05 owner.**)*

**Also produced:** `docs/decisions/0003-model-training-and-artifacts.md` (ADR). 21 new tests in `ml/tests/test_training.py` (88 in the whole repository, all passing). A full run takes 45.6 s.

## 8. Handoff note template

> Three trained model artifacts available at: <paths>, each following the Section 5 bundle contract. Experiment log at: <path>. Best hyperparameters per model: <summary>. Class imbalance strategy used: <summary>. Part 05 can now run final evaluation against the held-out test set.

**Filled in:** see §9 of [`docs/ml/training.md`](../docs/ml/training.md).
