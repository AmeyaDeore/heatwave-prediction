# Model evaluation and selection (Part 05)

This part scores the three Part 04 candidates on the held-out test split, once. It then applies a selection policy that was committed before the scoring, and records the chosen model as the production model in a small registry. Related documents:

- [training.md](training.md): how the candidates were trained and packaged (Part 04)
- [../decisions/0004-model-selection-and-registry.md](../decisions/0004-model-selection-and-registry.md): why the policy, the registry and the guards are what they are
- [`ml/registry/evaluations/20260929T081440Z-ecce7f/report.md`](../../ml/registry/evaluations/20260929T081440Z-ecce7f/report.md): the full generated report (every table, reliability bins, selection trace)

```sh
uv run heatwave-evaluate run [--run ID]           # score a training run on test, once; select
uv run heatwave-evaluate verify [--evaluation ID] # re-derive a report from bundles + dataset
uv run heatwave-evaluate show [--evaluation ID]
uv run heatwave-registry promote --evaluation ID  # make the selection the production model
uv run heatwave-registry rollback --to VERSION --reason TEXT
uv run heatwave-registry status | verify
```

## 1. Code layout

```
config/model_selection.yaml         the selection policy (committed before any test scoring)
heatwave_ml/registry.py             SHARED with the backend: production pointer, history, resolve
heatwave_ml/evaluation/
  settings.py    EvaluationSettings (MODEL_SELECTION_POLICY, MODEL_REGISTRY_DIR, ...)
  metrics.py     per-class/aggregate scores, failure modes, calibration, cost, paired bootstrap
  latency.py     interleaved latency benchmark + exact-SHAP explanation preview
  policy.py      SelectionPolicy (the YAML) and select(): gates → tier → cost → latency
  evaluator.py   load → score test once → benchmark → select → write report; verify
  report.py      report.md and the templated justification paragraph
  cli.py         heatwave-evaluate, heatwave-registry
ml/registry/                        committed (unlike ml/artifacts/)
  production.json                   THE pointer Part 07 loads
  history.jsonl                     append-only: evaluated · promoted · rolled_back
  evaluations/<id>/report.{json,md}
```

## 2. Selection criteria, fixed before the numbers (Part 05 §3)

The criteria are a config file, [`config/model_selection.yaml`](../../config/model_selection.yaml) (`SEL-v1`), rather than prose. That makes them executable and makes their timing provable:

- The policy was committed on its own in `fbdf161` at **2026-09-29 07:53 UTC**. The only test-split scoring happened at **08:14 UTC**, with evaluator code from the clean commit `71dd36d`. The report records both commits.
- `heatwave-evaluate run` **refuses to run** while the policy file has uncommitted changes. Changing the criteria after seeing numbers would therefore need a new commit and a new `policy_version`, both visible in history.
- Before writing the policy, calibration and latency were measured on the **validation** split only (top-label ECE 0.008 to 0.022; single-row predict about 8 ms for XGBoost and 170 ms for Random Forest). That kept the thresholds realistic without any test-split peeking.

The policy applies four steps in order. Rationale:

| Step | Rule (SEL-v1) | Plan criterion | Why this form |
|---|---|---|---|
| 1. Gates | SEVERE_HEATWAVE → NORMAL = **0** · top-label ECE ≤ **0.05** · p95 request (predict + explain one row) ≤ **500 ms** · an exact SHAP explainer exists | §3.3, §2 calibration, §3.4, §3.5 | These are pass/fail properties, not trade-offs. No accuracy gain can buy back a severe day with no warning at all. The UI's "confidence" must mean what it says. The API must answer inside a 1-second dashboard interaction. Part 06 needs exact per-request SHAP values. |
| 2. Quality tier | Keep every candidate that is **not significantly worse** than the best on macro-F1 **and** accuracy (paired bootstrap, 2,000 resamples, 95 %) | §3.1 (primary signal) | With 746 test rows (64 SEVERE), differences under about 1 point are noise. A fixed margin would be arbitrary, whereas the bootstrap asks the data how big a real difference is. Macro-F1 is used because accuracy alone rewards "always NORMAL" (81 %). |
| 3. Operational cost | Lowest mean cost per prediction, from a cost matrix (rows = truth): NORMAL `[0, 1, 2]`, HEATWAVE `[5, 0, 1]`, SEVERE `[20, 3, 0]` | §3.2 (severe misses weigh most) | A cost matrix states "how much worse" explicitly, per error type: a missed severe day costs 20 false alarms, and an under-graded one (a warning issued, but no cooling centres) costs 3. Per-class recall alone can't tell a severe → NORMAL miss from a severe → HEATWAVE one. |
| 4. Latency tie-break | Among candidates whose cost is not significantly higher than the lowest, pick the fastest **if** it is ≥ **2×** faster per request | §3.4 ("near-identical accuracy but materially faster") | "Material" needs a number. Below 2×, run-to-run and machine noise can reverse the order. |
| Check | Re-run steps 1–4 under an all-errors-equal matrix and a severe-dominant one (SEVERE `[50, 10, 0]`) | §4 (defensible) | Shows whether the choice rests on the exact cost values. It never changes the selection. |

The cost values are a judgment, not a measurement. The sensitivity check exists so that the judgment's influence is visible.

## 3. Results: evaluation `20260929T081440Z-ecce7f`

Training run `20260928T100821Z-0bde51`. Test split: 746 rows of dataset `7412ab78…09ecd` (NORMAL 604, HEATWAVE 78, SEVERE_HEATWAVE 64), scored once.

### 3.1 Comparison table (Part 05 §4)

Precision, recall and F1 are **macro** averages: each class counts equally, so the rare classes are not hidden behind NORMAL.

| Model | Accuracy | Precision | Recall | F1 Score |
|---|---|---|---|---|
| Logistic Regression | 0.9062 | 0.7833 | 0.9055 | 0.8313 |
| Random Forest | 0.9383 | 0.8393 | 0.9206 | 0.8756 |
| **XGBoost (selected)** | **0.9437** | **0.8524** | 0.9145 | **0.8809** |

Weighted averages (by test support), precision / recall / F1: Logistic Regression 0.9324 / 0.9062 / 0.9139 · Random Forest 0.9461 / 0.9383 / 0.9407 · XGBoost 0.9488 / 0.9437 / 0.9454.

### 3.2 Per-class (Part 05 §2)

| Class | Metric | Logistic Regression | Random Forest | XGBoost |
|---|---|---|---|---|
| NORMAL (604) | P / R / F1 | 0.995 / 0.907 / 0.949 | 0.990 / 0.947 / 0.968 | 0.988 / 0.957 / **0.972** |
| HEATWAVE (78) | P / R / F1 | 0.576 / **0.872** / 0.694 | 0.733 / 0.846 / 0.786 | 0.756 / 0.833 / **0.793** |
| SEVERE_HEATWAVE (64) | P / R / F1 | 0.779 / 0.938 / 0.851 | 0.795 / **0.969** / 0.873 | 0.813 / 0.953 / **0.878** |

### 3.3 Confusion matrices and the dangerous failure mode

| | LR | RF | XGBoost |
|---|---|---|---|
| **SEVERE → NORMAL** (no warning at all) | **0** / 64 | **0** / 64 | **0** / 64 |
| SEVERE → HEATWAVE (under-graded) | 4 | 2 | 3 |
| HEATWAVE → NORMAL (missed) | 3 / 78 | 6 / 78 | 7 / 78 |
| NORMAL → HEATWAVE / → SEVERE (false alarms) | 46 / 10 | 22 / 10 | 18 / 8 |

No model ever predicts a severe day as NORMAL, so the dangerous failure mode is ruled out for all three. Where they differ: RF and XGBoost trade 3 to 4 more missed HEATWAVE days than LR for 24 to 30 fewer false alarms. Between RF and XGBoost the error mix differs, but the cost-weighted total is identical: **84 cost points each** (0.1126 per prediction).

### 3.4 Calibration (the "prediction confidence" of Part 12)

| Model | Mean confidence | Accuracy | Top-label ECE | Brier | Log loss |
|---|---|---|---|---|---|
| Logistic Regression | 0.946 | 0.906 | 0.040 | 0.130 | 0.257 |
| Random Forest | 0.955 | 0.938 | **0.018** | 0.080 | **0.127** |
| XGBoost | 0.970 | 0.944 | 0.028 | **0.079** | 0.134 |

All three pass the 0.05 gate. For XGBoost, 677 of 746 predictions (91 %) are made at over 90 % confidence, and those are right 97.9 % of the time. The 69 predictions below 90 % are off by 4 to 24 points per bin, and mostly overconfident (for example 0.857 claimed against 0.682 observed; only the 0.7–0.8 bin is slightly underconfident). **For Part 12:** a confidence under about 90 % should be presented as "uncertain", not read literally. If Part 12 needs literal probabilities, fit an isotonic calibrator on the **validation** split and re-evaluate it as a new model version. The test split must not be used for that.

### 3.5 Inference latency (Part 05 §3.4)

Measured through `ModelBundle.predict_proba` on training rows. The candidates were interleaved round-robin and the process ran at high priority.

| Model | Bundle | Predict 1 row p50 / p95 | Predict 15 rows p50 / p95 | SHAP explain 1 row p50 / p95 | Request p95 |
|---|---|---|---|---|---|
| Logistic Regression | 0.01 MB | 7.1 / 11.4 ms | 7.1 / 9.9 ms | 6.1 / 11.1 ms (Linear) | 22.5 ms |
| Random Forest | 14.3 MB | 37.6 / 57.5 ms | 38.5 / 46.1 ms | 19.1 / 28.5 ms (Tree) | 86.0 ms |
| XGBoost | 0.7 MB | 6.7 / 11.8 ms | 7.0 / 12.6 ms | 7.7 / 9.3 ms (Tree) | **21.1 ms** |

**Caveat, found while building this:** on this laptop, which is on battery, Windows throttles background processes. The same predict call measured 3.9 ms, and then 38 ms minutes later. That is why the benchmark interleaves candidates (they share whatever the machine is doing, so their *ratio* is fair) and why the run was made at high priority. The absolute numbers are specific to this laptop at this time. Part 07 and Part 18 must re-benchmark on the serving host. The decision uses the ratio (4.1×) against a 2× threshold, which leaves a wide margin.

### 3.6 Uncertainty

Paired bootstrap 95 % intervals: RF − XGBoost macro-F1 −0.005 [−0.026, +0.016], and accuracy −0.005 [−0.016, +0.005]. RF and XGBoost are **statistically indistinguishable** on every quality metric. One SEVERE test row is worth 1.6 points of severe recall, so RF's 0.969 against XGBoost's 0.953 is a single day. LR is significantly worse: macro-F1 −0.050 [−0.080, −0.021], and accuracy −0.038 [−0.055, −0.022].

## 4. Justification

Generated from the selection trace and stored in the report:

> Under policy SEL-v1, all 3 candidates passed the hard gates: none predicted a SEVERE_HEATWAVE day as NORMAL, all were calibrated within the top-label ECE limit, all fit the per-request latency budget, and all have an exact SHAP explainer. On the primary signal (macro-F1 and accuracy), XGBoost scored the highest macro-F1 (0.8809); Logistic Regression is significantly lower on f1_macro (−0.0496, 95 % CI [−0.0796, −0.0210]) and accuracy (−0.0375, 95 % CI [−0.0550, −0.0215]), so the quality tier is Random Forest, XGBoost. Weighting errors by operational cost (a missed SEVERE_HEATWAVE day costs 20, an under-graded one 3, a missed HEATWAVE 5, a false alarm 1-2), Random Forest has the lowest expected cost (0.1126 per prediction, SEVERE_HEATWAVE recall 0.969); XGBoost costs 0.1126 (not significantly more, 95 % CI of the difference [−0.0174, 0.0201]). Because XGBoost is operationally equivalent on cost and 4.1x faster per request (p95 21.1 ms against 86.0 ms; the policy's threshold is 2x), the latency tie-break selects it. XGBoost (xgboost-20260928T100821Z-0bde51) is therefore selected: accuracy 0.9437, macro-F1 0.8809, SEVERE_HEATWAVE recall 0.953 with 0 of 64 severe days predicted NORMAL, top-label ECE 0.0279, and a p95 request time of 21.1 ms with an exact TreeExplainer for Part 06. The choice is unchanged under every alternative cost matrix in the sensitivity check.

(Random Forest is listed as "lowest" only because the two costs are exactly equal and ties go to the earlier candidate.)

**On "Random Forest is the documented best performer".** The project brief states that Random Forest wins, and Part 05 §4 asks for that conclusion to be *reproducible and defensible, not just asserted*. On this data it is half-supported. Random Forest is statistically tied with XGBoost for best: its quality, cost and dangerous-miss record are equivalent, and it is slightly better calibrated. It is not uniquely best, however. With quality tied, the plan's own criteria 4 and 5 decide: XGBoost is 4× faster per request, its SHAP explanations are 2.5 to 3× faster, and its bundle is 20× smaller (0.7 MB against 14 MB). Criterion 5 is satisfied either way, since both are tree models with an exact TreeExplainer. The policy was fixed before this outcome was known, so the result was not steered.

If the team needs the shipped model to match the brief's wording, the registry supports that as a recorded override rather than a silent edit:
`uv run heatwave-registry promote --evaluation 20260929T081440Z-ecce7f --model random_forest-20260928T100821Z-0bde51 --reason "<why>"`.
Random Forest passes every gate, so the promotion is allowed. The pointer and history would then show `override: true` with that reason.

## 5. Production model and registry (Part 05 §5-6)

**Promoted:** `xgboost-20260928T100821Z-0bde51` by Ameya Deore on 2026-09-29, `selected_by_policy: true`. Recorded in [`ml/registry/production.json`](../../ml/registry/production.json) and [`ml/registry/history.jsonl`](../../ml/registry/history.jsonl).

- **The pointer is explicit.** Nothing selects a model by file name or recency. The backend default `MODEL_VERSION=production` means "read `production.json`". The old `latest` default was removed, because "newest" is exactly the implicit assumption §5 rules out. An exact version id in `MODEL_VERSION` pins one instead.
- **Version identifier.** `model_version` = `<family>-<training run id>` ties the bundle to its experiment-log run. The pointer also records `model_sha256` (content identity), `training_data.sha256` (the Part 03 dataset version) and `labeling_rule_version`.
- **What the pointer carries for Part 07/14:** bundle path, SHA-256, explainer type, and the test metrics (overall and per class) plus calibration. Part 14's model-performance panel is static per model version, served from here and never recomputed.
- **Loading:** `ModelRegistry(registry_dir, runs_dir).load_production()` returns `(ModelBundle, pointer)`. It refuses a bundle whose SHA-256 differs from the pointer, on top of `ModelBundle.load`'s own checks.
- **Archived, not deleted.** Random Forest and Logistic Regression remain in `ml/artifacts/runs/20260928T100821Z-0bde51/`, and their full results are in the evaluation report. `heatwave-registry status` lists them as `archived`. Nothing in this part deletes a bundle, and `save_bundle` refuses to overwrite one.
- **Fresh clones.** Bundles are git-ignored and the registry is committed. After `uv run heatwave-train run`, training is bit-for-bit reproducible, so `resolve` finds the rebuilt bundle by SHA-256 under its new run id. `uv run heatwave-registry verify` then confirms the pointer loads.

### Retraining: how the pointer is replaced

1. Train: `uv run heatwave-train run` (a new run id; new data means a new dataset SHA-256 from Part 03).
2. Evaluate: `uv run heatwave-evaluate run --run <new run id>`. **The current production model is included automatically as the champion** if it was trained on the same dataset version, so a retrain has to beat or tie it under the same policy. If the dataset changed, the champion is not re-scored (its training rows may overlap the new test split), and the report says so.
3. Review `ml/registry/evaluations/<id>/report.md`, then `uv run heatwave-registry promote --evaluation <id>`. Promotion is its own explicit, attributed event (Part 18 §4: model promotion is separate from code deployment). A candidate that failed a gate cannot be promoted, and promoting anything other than the policy's choice needs `--reason` and is logged as an override.
4. Rebuild the explainer against the new pointer: `uv run heatwave-explain build` ([explainability.md §8](explainability.md#8-versioning-and-lifecycle-part-06-8)). The backend refuses to start with a stale one. Then restart the backend (Part 07 §5).
5. **Rollback:** `uv run heatwave-registry rollback --to <previous version> --reason "<why>"`. The target must have been evaluated and must pass the gates, and its bundle must still resolve. Then run `uv run heatwave-explain build` again, as in step 4.

Changing the criteria: edit `config/model_selection.yaml`, bump `policy_version`, and commit that on its own **before** the next evaluation.

## 6. Test-set discipline and reproducibility (Part 05 §7)

- **Scored once.** Part 04 never loaded the test split. `heatwave-evaluate run` scores each model on it in a single pass, and records a `comparison_key` (dataset hash + model hashes + policy version). A second `run` of the same comparison is refused. Only `--repeat-reason "<why>"` can repeat it, and the reason is written into the new report.
- **Reproducible from artifacts + dataset alone.** `uv run heatwave-evaluate verify` reloads the bundles and dataset, re-scores, and checks every metric, confusion matrix, calibration table, bootstrap interval, selection step and sensitivity result for exact equality with `report.json`. No retraining is involved. Latency is recorded rather than re-derived (it depends on the machine), and the selection is re-derived from the recorded timings. Status on 2026-09-29: `ok … re-derived identically for 3 models`. `verify` re-reads test rows to *check* a finished report. It cannot change a decision, so it is not a second look.
- **Test prediction fingerprints** (SHA-256 of the float64 test probabilities) are in the report, for bit-level comparison later.

## 7. Limitations

- The data is the Part 03 synthetic set (IMD-calibrated). These are test scores on held-out synthetic rows, not a field validation. The open Part 03 items (forecast-lead error, Open-Meteo vs IMD bias) still apply to live use.
- 64 SEVERE test rows: each one is 1.6 points of recall. The bootstrap intervals in §3.6 are the honest precision of every comparison here.
- Latency comes from a laptop (§3.5). Re-benchmark on the serving host before relying on absolute times.

## 8. Handoff note (Part 05 → Part 06)

> Selected production model: **XGBoost, `xgboost-20260928T100821Z-0bde51`** (model SHA-256 `31f5f4c7…21c1aa57`, trained on dataset `7412ab78…09ecd`, rule `IMD-HW-DAILY-v1`), located at `ml/artifacts/runs/20260928T100821Z-0bde51/xgboost/` and recorded in the registry pointer `ml/registry/production.json` (load with `heatwave_ml.registry.ModelRegistry.load_production()`). Comparison table: §3.1 above. Test macro-F1 0.881, accuracy 0.944, SEVERE_HEATWAVE recall 0.953 with 0 of 64 severe days predicted NORMAL, top-label ECE 0.028. Full report: `ml/registry/evaluations/20260929T081440Z-ecce7f/report.md`. Justification: all three candidates passed the gates; Logistic Regression was significantly worse on macro-F1 and accuracy; Random Forest and XGBoost were statistically tied on quality and had identical operational cost (0.1126 per prediction); XGBoost is 4.1× faster per request (p95 21 ms against 86 ms) and one-twentieth the size, so policy SEL-v1's latency tie-break selects it, and the choice holds under both alternative cost matrices. **Part 06 should build the SHAP explainer against this specific artifact**: `shap.TreeExplainer` on the pipeline's `clf` step, fed the output of the `pre` step. The benchmark's preview measured 7.7 ms p50 per row. Version the explainer with this `model_sha256`, and rebuild it whenever `production.json` changes.
