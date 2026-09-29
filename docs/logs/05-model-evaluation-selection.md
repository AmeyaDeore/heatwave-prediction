# Log 05 — Model evaluation and selection

| | |
|---|---|
| Plan | [Implementation/05-model-evaluation-selection.md](../../Implementation/05-model-evaluation-selection.md) |
| Status | Complete |
| Date | 2026-09-29 |
| Branch / commits | `part-05/model-evaluation-selection` · `fbdf161` (policy) → `71dd36d` (code) → `e5ead11` (results, promotion, docs). Not yet pushed / PR not opened |
| Tests | 27 new (`ml/tests/test_evaluation.py`), 115 total |

## Summary

Scored the three Part 04 candidates on the held-out test split exactly once, under a selection policy committed *before* the scoring; produced the comparison table and justification; and formally promoted **XGBoost `xgboost-20260928T100821Z-0bde51`** to production through a new committed model registry. Random Forest and Logistic Regression are archived, not deleted.

## What was built

| Path | Role |
|---|---|
| `config/model_selection.yaml` | Policy `SEL-v1`: gates, quality tier, cost matrix, latency tie-break, sensitivity matrices, bootstrap/latency settings |
| `ml/src/heatwave_ml/evaluation/metrics.py` | Per-class + macro/weighted metrics, failure-mode counts, calibration (reliability tables, ECE, MCE, Brier, log loss), expected cost, paired bootstrap |
| `evaluation/policy.py` | `SelectionPolicy` (validated YAML) and pure `select()`: gates → tier → cost → latency |
| `evaluation/latency.py` | Interleaved round-robin benchmark (single row, 15-row batch, SHAP explain preview), GC off while timing |
| `evaluation/evaluator.py` | Load → score test once → benchmark → select → sensitivity → write report; `verify()` re-derives a report |
| `evaluation/report.py` | `report.md` rendering and the templated justification paragraph |
| `evaluation/cli.py` | `heatwave-evaluate run / show / verify`, `heatwave-registry status / promote / rollback / verify` |
| `ml/src/heatwave_ml/registry.py` | **Shared with the backend:** production pointer, append-only history, promote/rollback guards, bundle resolution by SHA-256, `load_production()` |
| `ml/registry/` (committed) | `production.json`, `history.jsonl`, `evaluations/20260929T081440Z-ecce7f/report.{json,md}` |

**Config/env:** `MODEL_SELECTION_POLICY`, `MODEL_REGISTRY_DIR` (ml); backend default changed from `MODEL_VERSION=latest` to `production` (follow the pointer) and gained `MODEL_REGISTRY_DIR`. The local `backend/.env` was aligned. Registry JSON excluded from detect-secrets (SHA-256 only).

**Docs:** `docs/ml/evaluation.md`, ADR `docs/decisions/0004-model-selection-and-registry.md`, `ml/registry/README.md`; updated `config/README.md`, `ml/README.md`, `ml/artifacts/README.md`, `docs/README.md`, `docs/configuration-and-secrets.md`, Part 05 checklist.

## Key decisions and why

- **Criteria as a committed file, before the numbers:** policy committed alone at 07:53 UTC; test scored at 08:14 UTC. The evaluator refuses to run on an uncommitted policy and records the commit. Thresholds were set from **validation**-only probes (ECE 0.008–0.022; RF ~170 ms vs XGBoost ~8 ms per predict).
- **Four steps:** (1) gates — SEVERE→NORMAL = 0, top-label ECE ≤ 0.05, p95 predict+explain ≤ 500 ms, exact SHAP explainer; (2) quality tier — not significantly worse on macro-F1 and accuracy (paired bootstrap, 2,000 resamples, 95 %); (3) lowest mean cost from a matrix (missed severe 20, under-graded severe 3, missed heatwave 5, false alarm 1–2); (4) among cost-equivalent models, a ≥ 2× faster one wins. Plus a sensitivity check under two alternative cost matrices.
- **Test split read once per comparison:** a comparison key (dataset + model hashes + policy version) blocks re-runs unless `--repeat-reason` is given and recorded.
- **Registry instead of MLflow:** a JSON pointer + history is enough for this scale, diffable and readable without unpickling. Promotion is explicit and attributed; gate failures can't be promoted; overrides need a reason; rollback targets must have been evaluated.
- **Retrains are challengers:** the current production model is automatically re-scored as champion when trained on the same dataset version.

## Results (evaluation `20260929T081440Z-ecce7f`, 746 test rows)

| Model | Accuracy | Precision | Recall | F1 (macro) | SEVERE recall | SEVERE→NORMAL | ECE | Request p95 |
|---|---|---|---|---|---|---|---|---|
| Logistic Regression | 0.9062 | 0.7833 | 0.9055 | 0.8313 | 0.938 | 0 | 0.040 | 22.5 ms |
| Random Forest | 0.9383 | 0.8393 | 0.9206 | 0.8756 | 0.969 | 0 | 0.018 | 86.0 ms |
| **XGBoost (selected)** | **0.9437** | **0.8524** | 0.9145 | **0.8809** | 0.953 | 0 | 0.028 | **21.1 ms** |

All three passed the gates. LR was significantly worse; RF and XGBoost were statistically tied on quality and had **identical** cost (84 points each, 0.1126 per prediction); XGBoost is 4.1× faster per request, so the tie-break selected it. Same result under both alternative cost matrices.

## Verification

- `heatwave-evaluate verify`: every metric, calibration table, interval, selection step and sensitivity result re-derived identically from bundles + dataset (no retraining).
- `heatwave-registry verify`: all three bundles present and hash-intact; production pointer resolves and loads.
- 27 tests: metrics vs sklearn, bootstrap pairing, calibration, every gate, tier, cost, latency tie-break, report writing, once-only rule, verify tamper detection, promote/override/rollback, gate-failure refusal, SHA-256 resolution, champion inclusion, CLIs. Full suite 115 passing; all pre-commit hooks pass.

## Deviations from the plan and issues found

- **Outcome differs from the brief:** the brief names Random Forest as best; on this data RF is *tied* for best, and XGBoost wins the pre-committed latency tie-break. A recorded override path to RF exists (`heatwave-registry promote … --model random_forest-… --reason …`).
- **Latency measurement was unstable on the laptop:** on battery, Windows throttled the background process (same call 3.9 ms, then 38 ms). Fixed by interleaving candidates in the benchmark and running the evaluation at high priority; absolute times are machine-specific.
- Tests caught a ragged cost-matrix row crashing in numpy instead of giving a clear error — fixed in the validator.
- Console output switched from `…` to `...` (mojibake on the Windows console).

## Open items / follow-ups

- Re-benchmark latency on the serving host (Parts 07/18).
- XGBoost confidence below ~90 % is mostly overconfident (4–24 points per bin): Part 12 should show it as "uncertain", or fit an isotonic calibrator on validation as a new model version.
- Push the branch and open the PR with the Part 05 handoff note.

## Handoff

Production model: XGBoost `xgboost-20260928T100821Z-0bde51` (SHA-256 `31f5f4c7…21c1aa57`), recorded in `ml/registry/production.json`; load with `ModelRegistry.load_production()`. Part 06 builds a `shap.TreeExplainer` on the pipeline's `clf` step (fed the `pre` step's output; preview 7.7 ms p50 per row), versioned with this `model_sha256`, rebuilt whenever the pointer changes.
