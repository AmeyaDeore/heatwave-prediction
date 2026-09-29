# Part 05 — Model Evaluation & Selection

**Depends on:** 04 (model training)
**Feeds into:** 06 (SHAP), 07 (backend API — consumes the selected model)
**Owner persona:** ML engineer

## 1. Objective

Evaluate the three trained candidate models against a single, fair, held-out test set; select the one to ship; and produce the documentation/report artifacts referenced elsewhere in the project (the comparison table shown in the results slide).

## 2. Metrics to compute (matching the brief exactly)

For each of the three models, compute, on the held-out test set only:
- **Accuracy**
- **Precision**
- **Recall**
- **F1-score**

Compute these **per class** (Normal / Heatwave / Severe Heatwave) as well as an overall/weighted figure — the overall number can hide poor performance on the rarer, more operationally important Heatwave and Severe Heatwave classes, so per-class figures must be part of the report even if the headline table only shows aggregates.

Also produce, as supporting artifacts (not necessarily headline numbers, but needed for a defensible selection):
- A confusion matrix per model, to see specifically what each model confuses (e.g., is Severe Heatwave ever misclassified as Normal, which would be a dangerous failure mode for an early-warning system — versus being misclassified as Heatwave, which is a lower-severity miss).
- Prediction probability calibration — since the system exposes a "prediction confidence" to end users (see Part 12), check that predicted probabilities are reasonably well-calibrated (a model saying "91% confidence" should be right close to 91% of the time it says that), not just that the top class is usually correct.

## 3. Selection criteria (documented reasoning, not just "highest F1")

Define, before looking at final numbers, what would justify choosing one model over another:
1. Overall F1-score and accuracy as the primary quantitative signal.
2. Per-class recall on Severe Heatwave weighted more heavily than other classes, since missing a severe event (false negative) is more operationally costly for an early-warning system than a false alarm.
3. Confusion matrix inspection — specifically ruling out the dangerous failure mode described above.
4. Inference latency — since predictions will be served live through an API (Part 07), a model with near-identical accuracy but materially faster inference may be preferable; record inference time per model on a representative batch.
5. Explainability quality/practicality (a preview of Part 06) — tree-based models pair well with fast, exact SHAP TreeExplainer computation, which matters if explanations must be generated per-request in the live API.

## 4. Documented comparison output

Produce the model comparison table referenced in the project results (Model / Accuracy / Precision / Recall / F1 Score, one row per model), plus a short written justification paragraph for the final choice, referencing the criteria in Section 3, not just the raw numbers. Based on the project's own findings, Random Forest is the documented best performer — but this plan's job is to make sure that conclusion is reproducible and defensible, not just asserted.

## 5. Final model selection & promotion

- Formally mark one model artifact (from Part 04's outputs) as "the production model" — this should be an explicit, recorded action (e.g., a pointer/alias file or a registry entry), not an implicit assumption based on file naming.
- Record the model version identifier that Part 07's backend will load, so there is never ambiguity about which artifact is currently live.
- Keep the other two candidate artifacts and their evaluation results archived (not deleted) — they're valuable if the production model needs to be rolled back or re-compared later.

## 6. Model versioning & registry approach

- Even for a mini-project, adopt a lightweight registry convention: each artifact bundle gets a unique version identifier tied to the training run that produced it (from Part 04's experiment log) and the dataset version it was trained on (from Part 03).
- Define how a future retraining event replaces the production pointer — this is what makes the system maintainable beyond the initial mini-project scope (e.g., if new IMD/NASA POWER data becomes available later and the model needs periodic retraining).

## 7. Non-functional requirements

- Evaluation must run against the test set exactly once per final model comparison — repeatedly "peeking" at test-set performance while iterating in Part 04 defeats the purpose of a held-out set; if iteration is needed, it should happen against the validation set instead, with the test set reserved for this final report only.
- The evaluation report must be reproducible from the artifacts and dataset alone, without needing to re-run training.

## 8. Acceptance criteria / "done"

- [x] Accuracy/Precision/Recall/F1 computed for all three models on the held-out test set, both overall and per-class. *(Evaluation `20260929T081440Z-ecce7f`, 746 test rows scored once: macro and weighted P/R/F1, accuracy and per-class P/R/F1, with 95 % paired-bootstrap intervals. Also calibration (top-label and per-class reliability, ECE, Brier, log loss): all three pass ECE ≤ 0.05. `docs/ml/evaluation.md` §3.)*
- [x] Confusion matrices produced and reviewed for the dangerous-failure-mode check. *(SEVERE_HEATWAVE → NORMAL is **0 of 64 for all three**, and it is a hard gate in the policy. Under-grades, missed HEATWAVE days and false alarms are counted separately and weighted by the cost matrix. §3.3.)*
- [x] Inference latency benchmarked per model. *(Single row, a 15-row batch and a SHAP explanation preview, timed through `ModelBundle.predict_proba` with the candidates interleaved. Request p95: LR 22.5 ms, RF 86.0 ms, XGBoost 21.1 ms. Machine caveat in §3.5.)*
- [x] Selection criteria documented before final numbers were reviewed (or at minimum, documented alongside the final write-up with clear reasoning). *(`config/model_selection.yaml` SEL-v1 was committed alone in `fbdf161` at 07:53 UTC; the test split was scored at 08:14 UTC. The evaluator refuses to run on an uncommitted policy and records the commit. Rationale in §2.)*
- [x] Comparison table and justification paragraph produced. *(§3.1 and §4, and in `ml/registry/evaluations/20260929T081440Z-ecce7f/report.md`. `heatwave-evaluate verify` re-derives every number from bundles + dataset with no retraining.)*
- [x] Production model formally selected, versioned, and pointer/alias recorded. *(**XGBoost `xgboost-20260928T100821Z-0bde51`**, promoted with `heatwave-registry promote` into `ml/registry/production.json`, with the history in `ml/registry/history.jsonl`. The backend default is now `MODEL_VERSION=production`. Retraining and rollback procedure in §5.)*
- [x] Archived (non-production) candidate artifacts retained. *(The RF and LR bundles stay in `ml/artifacts/runs/20260928T100821Z-0bde51/` and are listed as `archived` by `heatwave-registry status`; `heatwave-registry verify` checks they are present and intact. Their results are in the evaluation report.)*

**Outcome vs the brief:** Random Forest and XGBoost are statistically tied on quality and have identical operational cost. XGBoost wins the pre-committed latency tie-break (4.1× faster per request). The brief's "Random Forest is best" is therefore reproduced as "tied for best", not as uniquely best. See `docs/ml/evaluation.md` §4, including the recorded-override path. **Also produced:** `docs/decisions/0004-model-selection-and-registry.md` (ADR), 27 tests in `ml/tests/test_evaluation.py` (115 in the whole repository, all passing).

## 9. Handoff note template

> Selected production model: <model name + version id>, located at: <path>. Comparison table: <summary/link>. Justification: <one-paragraph summary>. Part 06 should build the SHAP explainer against this specific artifact.

**Filled in:** see §8 of [`docs/ml/evaluation.md`](../docs/ml/evaluation.md).
