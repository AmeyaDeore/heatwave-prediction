# ADR 0003 — Model training pipeline and artifact format

**Status:** Accepted, 2026-09-28 (Part 04)

## Decisions

| Need | Choice | Why |
|------|--------|-----|
| Keep preprocessing identical at train and serve time | Preprocessor **inside** each model's sklearn `Pipeline` (`pre` → `clf`), pickled as one object | Nothing has to re-apply a transform correctly at inference. CV fits the imputer and scaler per fold for free, and a scaler can't be forgotten or fit on the wrong data. |
| Tuning without touching the test split | Stratified 5-fold CV on the **train** split. Test is dropped at load time. Validation is scored once per final model as a check. | Part 05 §7 needs one honest test evaluation. Removing test at the loader makes "peeking" impossible, not just discouraged. |
| Tuning objective | Macro-F1, with per-class recall and F1 and log loss logged for every trial | Accuracy rewards "always NORMAL" (81 %). Logging everything lets Part 05 re-rank by SEVERE_HEATWAVE recall without retraining. |
| Search strategy | Grid for LR (1 knob, 17 values), random search for RF (30 of 240) and XGBoost (40) | Proportionate to 3,500 rows. The whole run takes 45 s. |
| Class imbalance | Balanced class weighting for all three, no resampling | Native to every library, no synthetic or duplicated rows, and no serving-time step. The logged ablation shows +1.6 to +27 points of heatwave-class recall, for at most −0.009 macro-F1 (docs/ml/training.md §4). |
| Artifact format | One immutable directory per model: `model.joblib` (the fitted Pipeline) + `bundle.json` (the contract: version, dataset hash, ordered features, class mapping, preprocessing marker, library versions, prediction fingerprint) | joblib is sklearn's recommended persistence, and handles XGBoost's sklearn wrapper too. The JSON sidecar is readable by Part 05 reports and the backend without unpickling anything. |
| Loading safely | `ModelBundle.load` checks SHA-256 **before** unpickling, then library versions, feature order, classes and preprocessing | A pickle executes code on load. Version drift silently changes predictions. Feature-order mismatch is the classic silent inference bug. |
| Experiment tracking | Append-only JSON Lines, using the Part 02 log writer | Required to be "more than console output", but MLflow would be a server and a dependency for a 45-second, single-machine job. JSONL is greppable and diffable, and it survives crashes. |
| Version id | `<family>-<run_id>`, where run_id = UTC timestamp + 6 random hex digits | Sortable, and ties a bundle to its experiment-log run. Content identity comes from `model_sha256` and the prediction fingerprint. |

## Alternatives rejected

- **SMOTE or random oversampling** (`imbalanced-learn`): it adds a dependency and a training-only pipeline step that must not run at inference. Duplicated or synthetic rows also need extra care to keep out of CV validation folds. Weighting reaches the same goal natively.
- **XGBoost's native `save_model` JSON**: portable across XGBoost versions, but it stores the booster only, not the imputer and scaler. The single-Pipeline guarantee is worth more. The shared `uv.lock` pins identical versions in ml/ and backend/.
- **ONNX export**: removes the pickle risk but needs converters (`skl2onnx`, `onnxmltools`), and SHAP (Part 06) needs the native tree models anyway.
- **Early stopping for XGBoost on the validation split**: that would make validation part of the fit. `n_estimators` is tuned by CV instead.
- **Refitting on train + validation**: Part 04 §3.7 says the full *training* set. Keeping validation out preserves an independent check for Part 05's calibration work.

## Consequences

- Loading a bundle needs `heatwave_ml` importable (the pickled imputer is `heatwave_ml.features.SeasonalMedianImputer`). Part 07 already depends on `heatwave_ml.features`.
- Bundles are pinned to the scikit-learn and XGBoost versions in `uv.lock`. Upgrading either means retraining, and `load` enforces this.
- Artifacts are git-ignored. Training is bit-for-bit reproducible (identical `model.joblib` bytes across reruns), so a fresh clone rebuilds identical models with `heatwave-train run`, under a new run id.
