# Log 06 — SHAP explainability integration

| | |
|---|---|
| Plan | [Implementation/06-shap-explainability-integration.md](../../Implementation/06-shap-explainability-integration.md) |
| Status | Complete |
| Date | 2026-09-29 |
| Branch / commits | `part-06/shap-explainability` (branched from `part-05/model-evaluation-selection`) · `0d270d9` (label table) → `c9b5de9` (code + tests) → the artifact + docs commit that adds this log. Not yet pushed / PR not opened |
| Tests | 42 new (`ml/tests/test_explainability.py`), 157 total |

## Summary

Before starting, Part 05's checklist was re-verified against the repository:
- 115 tests passing, ruff clean;
- `heatwave-registry verify` passed (all three bundles intact, the pointer loads);
- `heatwave-evaluate verify` re-derived report `20260929T081440Z-ecce7f` identically.

Part 06 then added per-prediction SHAP explanations for the production XGBoost model:
- a frozen, committed, versioned explainer artifact;
- a single call for the backend that returns the prediction and its explanation together;
- a shared label table;
- automated consistency and domain-sanity checks that gate the build.

## What was built

| Path | Role |
|---|---|
| `config/feature_labels.json` | **Shared with backend and frontend:** feature labels, display unit, precision, sign; risk-class display names |
| `ml/src/heatwave_ml/features/schema.py` | Loads the table (`FEATURE_LABELS`/`FEATURE_UNITS` unchanged, plus `FEATURE_DISPLAY`, `RISK_CLASS_LABELS`); fails on drift |
| `ml/src/heatwave_ml/explainability/explainer.py` | `HeatwaveExplainer`: build/save/load, `explain()` → `Explanation` (prediction + contract), `load_production_explainer(registry)` |
| `explainability/summary.py` | Templated summary sentence, value/probability formatting |
| `explainability/sanity.py` | 6 hand-picked cases / 7 checks run through `build_features` |
| `explainability/builder.py` | Background sampling, additivity/agreement check, global importance, latency benchmark, save + `explainer_built` event, `verify` |
| `explainability/cli.py` | `heatwave-explain build · verify · show · explain` |
| `ml/src/heatwave_ml/registry.py` | `record_event()`; docstring lists `explainers/` |
| `ml/src/heatwave_ml/evaluation/cli.py` | `heatwave-registry verify` checks the production explainer; promote/rollback print the rebuild command |
| `ml/registry/explainers/xgboost-20260928T100821Z-0bde51/` (committed) | `explainer.json` (18.8 KB) + `background.csv` (100 rows, 4.4 KB) |
| `ml/registry/history.jsonl` | + `explainer_built` event |

**Config/env:** `SHAP_BACKGROUND_ROWS=100` added to `ml/.env.example`. The latency budget is read from `config/model_selection.yaml` (`gates.max_p95_request_ms`), so it is not a second setting.

**Docs:**
- New: `docs/ml/explainability.md` and ADR `docs/decisions/0005-shap-explainability.md`.
- Updated: `docs/README.md`, `docs/ml/evaluation.md` (retraining step 4 and rollback now run `heatwave-explain build`), `ml/README.md`, `ml/registry/README.md`, `ml/artifacts/README.md`, `config/README.md`, `frontend/README.md`, and the Part 06 checklist and handoff.

## Key decisions and why

- **Explainer:** TreeExplainer, interventional, over the model's own training rows. The choice follows the estimator type automatically, so a rollback to RF or LR still gets an exact explainer. Path-dependent mode was rejected because its reference is implicit and cannot be frozen (§4).
- **What is explained:** log(P(target)/P(NORMAL)), where target is the predicted class, or HEATWAVE for a NORMAL prediction. It is exactly additive in SHAP values, and "positive = more risk" holds for every prediction. SHAP 0.52 has no multiclass probability output for XGBoost. A brute-force probability-space alternative was prototyped (67 ms/row) and rejected.
- **Representation:** a signed `share_pct` (normalised by Σ|contribution|) for the bars, next to the raw `contribution`. All 7 factors are returned, and the pages choose how many to show.
- **Summary:** a deterministic template with no adjectives and `>99%` / `<1%` at the extremes (see the issues below for why).
- **Artifact:** manifest + background CSV committed under the registry. The SHAP object is rebuilt at load (not pickled) and checked against a stored 20-row probe. It is keyed by model SHA-256, so a stale explainer is refused at load.
- **Background:** 100 rows. Against 500 rows (5× slower), the top factor agrees on 97.3 % of validation rows and shares differ by 1.8 points on average.

## Verification

- `uv run heatwave-explain build` passed every check and saved the artifact:
  - **additivity** on 746 validation rows: max error 2.2 × 10⁻⁶ per class, 1.4 × 10⁻⁶ against the log P-ratio; probabilities bit-identical to `ModelBundle.predict_proba`;
  - **sanity:** 7/7 checks pass;
  - **latency:** p50 27.6 ms / p95 45.4 ms per request, 338 ms for 15 rows (budget 500 ms).
- `uv run heatwave-explain verify`: `ok` (loads for its model, reproduces its probe, the background equals a fresh sample, and every check re-derives).
- `uv run heatwave-registry verify`: the three bundles are intact, the pointer loads, and the production explainer matches and reproduces.
- `uv run heatwave-explain explain --rows 4 [--json]`: explanations were read by hand on real validation days (logged SEVERE and HEATWAVE examples are in `docs/ml/explainability.md` §7).
- Tests (`uv run pytest`): **157 passed**. The 42 new ones cover:
  - additivity and the log-ratio identity for all three families;
  - bundle agreement, the contract's shape, ranking and signs, both signs occurring, imputation flags, determinism;
  - that the whole background is used, and the float32 threshold floor;
  - save/load round trip, and stale, tampered and non-reproducing refusals;
  - pointer-following and stale-after-promotion;
  - builder idempotence, `--force`, and wrong-dataset refusal; the CLI;
  - the summary templates, and the label table and its drift check;
  - sanity cases, and the recorded build, on the real production model (skipped on a fresh clone without bundles).
- `uv run pre-commit run --all-files`: all hooks pass.

## Deviations from the plan and issues found

- **The model is XGBoost, not the brief's Random Forest** (a Part 05 outcome). The plan's "Random Forest → tree explainer" still holds, since both are tree models.
- **SHAP 0.52 refuses the interventional mode for XGBoost 3 models** because `enable_categorical=True` is the default, even with no categorical features. The booster is passed instead, after a guard that no feature is categorical.
- **SHAP silently subsamples any background over 100 rows** to 100 ("max_samples=100"). A background larger than 100 would therefore not have been what was frozen. Fixed with `maskers.Independent(max_samples=len)`, with a test (the unfixed baseline is off by 0.196).
- **Random Forest additivity was broken by up to 2.8 × 10⁻⁴.** Traced to one tree whose threshold (4.00999999) lies between two float32 values. SHAP rounds thresholds to the nearest float32 (4.01), so one background row went left in SHAP and right in scikit-learn, which shifted every sum by a leaf weight. Fixed by rounding tree inputs to float32 and flooring RF thresholds to float32. The error is now about 10⁻⁸. The production model was unaffected, but a rollback to RF would have shipped slightly wrong explanations.
- **Summary wording:** the first draft used "high/low" adjectives relative to the background median and produced "high maximum temperature (35.5 °C)" as a factor *keeping risk low*. Adjectives were dropped. "100% probability" for p = 0.9991 was replaced by ">99%".
- **SHAP's C extension printed progress bars** on long batch calls. Rows are now explained in chunks of 50. SHAP's own per-call additivity check (a slow Python re-prediction) is off; the explicit checks replace it.
- **The Part 05 CLI test was changed:** `heatwave-registry verify` now fails when production has no explainer. This is the intended behaviour, and the test asserts it.
- **Finding for the UI:** about 90 % of every explanation is temperature (global importance: deviation 48 %, Tmax 30 %, normal 11 %, humidity 4 %, solar 3 %, wind 2 %). The labels come from the temperature-only IMD rule, so this is correct. The mockup's "elevated humidity, limited wind dispersion" would overstate those factors for this model.

## Open items / follow-ups

- Part 07: add `heatwave-ml` as a backend dependency, load the explainer at startup (fail startup if it is stale or missing), and return `Explanation.to_dict()` unchanged from `POST /api/predict`. Re-measure latency on the serving host.
- Part 08: `prediction_factors` rows from `factors`; store `model_version` and `explainer_id` on `predictions`.
- Part 12: render `share_pct` and `direction` directly, mark `imputed` factors, and show the `summary` verbatim.
- For scheduled runs over all regions and days, explain in one batch call. The cost is linear in rows × background: 15 rows ≈ 0.34 s.
- **Branches:** Part 05 is still unmerged (`main` = `origin/main` = Part 04), and this branch is stacked on it. Push and open the Part 05 PR, then Part 06.

## Handoff

Explainer `xgboost-20260928T100821Z-0bde51+shap.2154641e` at `ml/registry/explainers/xgboost-20260928T100821Z-0bde51/`, built against production model `xgboost-20260928T100821Z-0bde51` (SHA-256 `31f5f4c7…21c1aa57`). Load it with `load_production_explainer(ModelRegistry(...))`, and call `explainer.explain(model_input(build_features(raw, normals)))` → `.to_dict()`. The contract is in `docs/ml/explainability.md` §3, and the label table is `config/feature_labels.json`. Per request: p50 27.6 ms / p95 45.4 ms for prediction plus explanation, measured on the dev laptop.
