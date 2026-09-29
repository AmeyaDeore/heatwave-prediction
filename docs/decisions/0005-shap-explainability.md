# ADR 0005 — SHAP explainability: explainer, contract and artifact

**Status:** Accepted, 2026-09-29 (Part 06)

## Decisions

| Need | Choice | Why |
|------|--------|-----|
| Exact, per-request explanations for the production model (Part 06 §2, §6) | `shap.TreeExplainer` for XGBoost and Random Forest, `LinearExplainer` for Logistic Regression, picked from the bundle's estimator type | Exact for these models, and ~28 ms per request for the production XGBoost against a 500 ms budget. Following the model type automatically means a rollback to an archived candidate still gets an exact explainer. |
| A frozen, inspectable reference (Part 06 §4) | Interventional mode over 100 seeded random rows of the model's **own** training split, committed as `background.csv` with its SHA-256 | Path-dependent mode has an implicit reference (tree node counts) that cannot be frozen or versioned. A simple random sample keeps the average training day as the baseline. The builder refuses any dataset except the one the bundle records. |
| One signed number per factor, "positive = more risk" (Part 06 §3), for a 3-class model | Explain log(P(target)/P(NORMAL)): target = predicted class, or HEATWAVE when NORMAL is predicted | Softmax margin differences are exactly additive in SHAP values, so the sign convention holds for every prediction. A NORMAL day is explained as "why not a heatwave". |
| A bar-ready representation (Part 06 §3, Part 12) | `share_pct` = 100 × contribution / Σ\|contribution\|, signed, alongside the raw `contribution` | Log-odds are not meaningful to an official, and SHAP has no probability output for multiclass XGBoost. Shares are the "normalised percentage" option Part 06 allows, and the raw value keeps additivity checkable. |
| Full list or top-N | All 7 factors, ranked. Pages choose how many to show | The dashboard (top 2–3) and the Prediction page (all) must never disagree. With 7 features, the full list costs nothing. |
| Summary sentence | Deterministic template naming factors with ≥ 5 % share, with their values and no adjectives; probabilities shown as `>99%` / `<1%` at the extremes | Testable and traceable. Adjectives relative to any median contradicted the SHAP sign ("high temperature … keeping risk low"). "100%" overstates a probabilistic model. |
| Label mapping (Part 06 §5) | `config/feature_labels.json`, loaded by `features/schema.py` with drift checks and exported for the backend and frontend | One table, JSON so the frontend can import it without a parser. The existing Python names (`FEATURE_LABELS`, `FEATURE_UNITS`) keep their values. |
| Artifact and versioning (Part 06 §8) | `ml/registry/explainers/<model_version>/{explainer.json, background.csv}`, committed. The SHAP object is rebuilt at load, not pickled. `explainer_built` events go in `history.jsonl` | Small, and reproducible on a fresh clone. It avoids pickles tied to one SHAP version. The manifest's model SHA-256 plus a 20-row probe let `load` refuse a stale or drifted explainer. |
| Stale-explainer safety | `load_production_explainer` refuses an explainer whose model SHA-256 isn't the pointer's model. `heatwave-registry verify` checks it, and promote/rollback print the rebuild command | A promotion or rollback without a rebuild fails loudly at backend startup instead of producing wrong explanations. |
| Prediction and explanation consistency | `explain()` predicts and explains from one preprocessing pass, and returns both | An explanation can never belong to a different prediction. The probabilities are checked bit-identical to `ModelBundle.predict_proba`. |

## Alternatives rejected

- **Path-dependent TreeExplainer:** faster and needs no background, but the reference is implicit, so it cannot satisfy Part 06 §4's frozen, versioned reference.
- **Exact Shapley values in probability space by brute force** (2⁷ coalitions × background): additive in probability points, but 67 ms per row, model-agnostic rather than a tree explainer, and it would duplicate what SHAP computes exactly.
- **Explaining only the predicted class's own margin:** for a NORMAL prediction, positive would mean "more NORMAL", which breaks the single sign convention the UI needs.
- **Pickling the SHAP explainer:** its format changes between SHAP releases, while rebuilding from the model and the background is deterministic and fast.
- **Serving global feature importance:** it answers a different question. It is recorded for Part 14, never served as a prediction's explanation.

## Consequences

- Three workarounds for SHAP 0.52 behaviour, each covered by a test:
  1. XGBoost 3's `enable_categorical=True` default makes SHAP refuse the interventional mode, so the booster is passed instead (after checking there are no categorical features).
  2. A bare background over 100 rows is silently subsampled, so it goes through `maskers.Independent(max_samples=len)`.
  3. SHAP rounds Random Forest thresholds to the nearest float32, which broke additivity by 2.8 × 10⁻⁴. Inputs are rounded to float32 and thresholds floored to float32.
- Explanations for this model are about 90 % temperature features, because the labels come from the temperature-only IMD rule. Humidity and wind appear, correctly, as minor factors.
- The explainer must be rebuilt (`uv run heatwave-explain build`) after every promotion or rollback. Part 07 fails startup otherwise.
