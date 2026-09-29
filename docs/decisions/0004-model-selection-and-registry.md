# ADR 0004 — Model selection policy and model registry

**Status:** Accepted, 2026-09-29 (Part 05)

## Decisions

| Need | Choice | Why |
|------|--------|-----|
| Criteria fixed before the numbers (Part 05 §3, §8) | The policy is a committed YAML file (`config/model_selection.yaml`), and the evaluator **refuses to run** while it has uncommitted changes. Each report records the policy's SHA-256 and last commit. | Prose criteria can't be checked and can be quietly reinterpreted after the fact. A file plus git history *proves* ordering, and the policy is executable, so the write-up can't drift from what was applied. |
| Rank candidates, not just threshold them | Four steps: hard **gates**, a **quality tier** by paired bootstrap, the lowest **operational cost** from a misclassification cost matrix, then a **latency tie-break** at ≥ 2× | Mirrors Part 05 §3's list in order. Gates capture the non-negotiables (the dangerous miss, calibration, latency budget, exact SHAP). The tier stops sampling noise from deciding. The cost matrix encodes "a severe miss costs more than a false alarm" per error type, which per-class recall can't express. The tie-break implements "near-identical accuracy but materially faster". |
| "Near-identical" and "significant" | Paired bootstrap, 2,000 resamples, 95 %, the same resampled rows for every model | 746 test rows and 64 SEVERE: one row is 1.6 points of severe recall. A fixed margin would be a guess, whereas pairing removes the between-model resampling noise. |
| Robustness of the cost judgment | Re-select under two alternative matrices and report agreement | Cost values are a judgment. Showing whether the choice flips makes that judgment's influence visible. |
| Test split read once (Part 05 §7) | The same comparison (dataset hash + model hashes + policy version) is refused a second time without a recorded `--repeat-reason` | Makes "peeking" a deliberate, logged act rather than an easy re-run. |
| Reproducible without retraining | `heatwave-evaluate verify` re-derives every deterministic number and the selection from bundles + dataset, and checks exact equality | Part 05 §7. Latency is recorded as an input, since it is machine-dependent. |
| Fair latency on a shared laptop | Candidates timed **interleaved** round-robin, with GC disabled during timing; the machine is recorded | Measured on this machine: the same call took 3.9 ms, then 38 ms (Windows throttles background processes on battery). Sequential timing would give one model the slow period. |
| The production pointer | A committed `ml/registry/production.json`, written only by `heatwave-registry promote` or `rollback`, with an append-only `history.jsonl` | Part 05 §5 wants an explicit, recorded action. A JSON file is readable by the backend without unpickling. Git history plus `history.jsonl` give attribution. Promotion is separate from code deployment (Part 18 §4). |
| Version identifier | `model_version` = `<family>-<run_id>` (from Part 04), plus `model_sha256` as content identity | The run id links to the experiment log, and the bundle records the dataset hash. Content identity survives a reproduced retrain. |
| Git-ignored bundles vs a committed pointer | `resolve()` uses the recorded path if its SHA-256 matches, otherwise any bundle of that family with the same SHA-256 | Training is bit-for-bit reproducible (Part 04 §8), so a fresh clone's `heatwave-train run` recreates the exact file under a new run id and the pointer still resolves. |
| Promotion safety | Gate failures can never be promoted. Promoting anything but the policy's selection needs `--reason` and is logged as `override: true`. Rollback targets must have been evaluated. | Humans can overrule the policy, but only visibly. |
| Backend default | `MODEL_VERSION=production` (follow the pointer); the old `latest` default was removed | "Latest" is the implicit, file-naming-based choice §5 forbids. |

## Alternatives rejected

- **"Highest macro-F1 wins".** Part 05 §3 explicitly asks for more than that, and here the top two differ by 0.005 with a 95 % interval of [−0.026, +0.016]: the ranking would be a coin toss.
- **A weighted composite score** (for example 0.5·F1 + 0.3·severe recall + 0.2·accuracy): the weights are as arbitrary as a cost matrix, but they mean nothing operationally, and a large F1 lead could buy back a dangerous miss. Gates plus cost are explainable to a disaster-management official.
- **MLflow Model Registry:** it needs a tracking server and a database for a three-model, single-machine project. The JSON pointer plus history holds the same information (stage, version, lineage, who and why) and is diffable in code review.
- **Choosing the model by file name or the newest run:** this is exactly the implicit assumption Part 05 §5 rules out.
- **Post-hoc calibration now:** all three candidates pass ECE ≤ 0.05. A calibrator would be a new model version needing its own evaluation. If Part 12 needs literal probabilities, it is fit on validation (see `docs/ml/evaluation.md` §3.4).

## Consequences

- The shipped model is **XGBoost**, not the Random Forest the project brief names. The two are statistically tied on quality and cost, and XGBoost wins the pre-committed latency tie-break (4.1× faster). The brief's claim is recorded as "tied for best", and a recorded override path exists if the team wants Random Forest.
- Part 06 builds a `TreeExplainer` against `production.json`'s bundle, and must rebuild whenever the pointer changes.
- Part 07 loads the model with `ModelRegistry.load_production()` and serves the static performance metrics from the pointer. It must re-benchmark latency on the serving host.
- Changing selection rules means a `policy_version` bump, in a commit that precedes the next evaluation.
