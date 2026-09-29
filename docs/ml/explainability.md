# SHAP explainability (Part 06)

Every prediction the system makes comes with the meteorological factors that drove it: a ranked, signed list of contributions plus a one-sentence summary. They are computed per request, in the same call as the prediction. This page covers the explainer, the output contract that Part 07 returns and Parts 08 and 12 consume, the frozen reference data, how the explainer is validated, and how it stays tied to the production model.

- Code: `ml/src/heatwave_ml/explainability/`
- Artifact: `ml/registry/explainers/<model_version>/` (committed)
- Label table: `config/feature_labels.json`
- Tests: `ml/tests/test_explainability.py`
- Why: [ADR 0005](../decisions/0005-shap-explainability.md)

```sh
uv run heatwave-explain build     # build + check + save the explainer for the production model
uv run heatwave-explain verify    # reload it and re-derive every check
uv run heatwave-explain show      # checks, global importance, latency
uv run heatwave-explain explain --rows 3 [--json]   # explain validation rows / print the contract
```

## 1. Code layout

| Module | What it does |
|---|---|
| `explainer.py` | `HeatwaveExplainer`: builds or loads the SHAP explainer for a bundle, and `explain()`, which returns prediction + explanation per row. Also `load_production_explainer(registry)`, the one call Part 07 makes. |
| `summary.py` | The templated summary sentence, and the value/probability formatting shared with the contract. |
| `sanity.py` | Hand-picked domain cases run through the live feature path (`build_features`), with their expectations. |
| `builder.py` | Freezes the background, runs every check (additivity, agreement, sanity, latency), records global importance, then saves and logs the artifact. `verify` re-derives it all. |
| `cli.py` | `heatwave-explain build · verify · show · explain`. |

## 2. Explainer choice and what is explained (Part 06 §2)

**Production model:** XGBoost `xgboost-20260928T100821Z-0bde51` (Part 05). **Explainer:** `shap.TreeExplainer`, which is exact for tree ensembles and fast enough to run per request (§6). The choice follows the model type automatically: XGBoost and Random Forest get `TreeExplainer`, and Logistic Regression gets `LinearExplainer`. So a rollback to an archived candidate gets its own exact explainer (all three are tested).

**Mode:** `feature_perturbation="interventional"` over a frozen background sample (§4). A contribution means "compared with a typical day from the training data". The alternative, path-dependent mode, needs no background and is faster. It was rejected because its reference is implicit (tree node counts), so it cannot be frozen, inspected or versioned as Part 06 §4 asks.

**The quantity explained.** The model has three outputs, one per class, but the dashboard needs one signed number per factor where positive means "more heat risk". Each prediction explains the **log-odds of a risk class against NORMAL**:

| Prediction | Target class | Explained quantity |
|---|---|---|
| SEVERE_HEATWAVE | SEVERE_HEATWAVE | log(P(SEVERE_HEATWAVE) / P(NORMAL)) |
| HEATWAVE | HEATWAVE | log(P(HEATWAVE) / P(NORMAL)) |
| NORMAL | HEATWAVE (the next level up: "why not a heatwave") | log(P(HEATWAVE) / P(NORMAL)) |

A softmax model's class margins are sums of per-class SHAP values, so the margin difference `target − NORMAL` is explained **exactly**. The explanation satisfies `baseline + Σ contributions = log(P(target)/P(NORMAL))` for every row. The sign convention is the same for every prediction: **a positive contribution pushes toward the risk class and a negative one toward NORMAL.** This is why Wind Speed shows as a negative, protective contribution on a windy heatwave day (§7).

Why not probability points? SHAP 0.52 has no probability-space output for multiclass XGBoost. Brute-force exact Shapley values in probability space (2⁷ coalitions × background) were prototyped: 67 ms per row, and model-agnostic rather than a tree explainer. They were rejected in favour of the exact tree explanation of log-odds, with display via normalised shares (§3).

## 3. The output contract (Part 06 §3)

`explainer.explain(inputs)` takes the output of `build_features` (the model's features plus `month`) and returns one `Explanation` per row. `.to_dict()` is what Part 07 returns:

```json
{
  "risk_class": "SEVERE_HEATWAVE",
  "confidence": 0.9965,
  "probabilities": {"NORMAL": 0.0007, "HEATWAVE": 0.0028, "SEVERE_HEATWAVE": 0.9965},
  "explanation": {
    "target_class": "SEVERE_HEATWAVE",
    "reference_class": "NORMAL",
    "quantity": "log_odds",
    "explained": "log(P(SEVERE_HEATWAVE) / P(NORMAL))",
    "baseline": -5.9547,
    "output": 7.2795,
    "factors": [
      {"rank": 1, "feature": "temp_deviation_c", "label": "Temperature Deviation", "unit": "°C",
       "value": 8.02, "display_value": "+8.0 °C", "imputed": false,
       "contribution": 8.9574, "share_pct": 65.0, "direction": "increases_risk"},
      {"rank": 2, "feature": "tmax_c", "label": "Maximum Temperature", "unit": "°C",
       "value": 42.6, "display_value": "42.6 °C", "imputed": false,
       "contribution": 4.4902, "share_pct": 32.6, "direction": "increases_risk"},
      "... all 7 features, ranked by |contribution| ..."
    ],
    "summary": "The model predicts Severe Heatwave conditions (>99% probability), mainly because of Temperature Deviation (+8.0 °C) and Maximum Temperature (42.6 °C).",
    "model_version": "xgboost-20260928T100821Z-0bde51",
    "explainer_id": "xgboost-20260928T100821Z-0bde51+shap.2154641e"
  }
}
```

| Field | Meaning |
|---|---|
| `risk_class`, `probabilities`, `confidence` | The prediction. Identical to `ModelBundle.predict_proba` (checked by the builder and the tests). `confidence` = the predicted class's probability. |
| `target_class`, `reference_class`, `quantity`, `explained` | What the contributions explain (§2). `quantity` is `log_odds` for XGBoost and LR, and `probability` for Random Forest, whose raw output is a probability. |
| `baseline` | The explained quantity for the average background day (SHAP expected value). `output` = `baseline` + Σ `contribution`. |
| `factors` | **The full ranked list: all 7 features**, ordered by \|contribution\| (ties keep the schema order). The dashboard shows the top 2–3 and the Prediction page shows all. Nothing is dropped server-side, so both pages agree. |
| `factors[].contribution` | Signed SHAP value in `quantity` units. `> 0` raises the risk and `< 0` lowers it. |
| `factors[].share_pct` | **The representation for the bars:** `100 × contribution / Σ|contributions|`, signed, 1 decimal. The absolute shares sum to 100 %, the bar length is `|share_pct|`, and the bar direction and colour come from the sign. Frontend code uses this field directly and never re-derives it (Part 12 §3). |
| `factors[].direction` | `increases_risk` / `decreases_risk` / `neutral` (exactly zero). |
| `factors[].value`, `display_value` | The value the model used (after imputation), and that value formatted with the shared table's unit and precision (`+7.4 °C`, `35%`). The summary sentence uses the same string. |
| `factors[].imputed` | `true` when the input was missing and was filled with the training median for that month. The UI should mark such a factor. |
| `summary` | Templated sentence (below). |
| `model_version`, `explainer_id` | Which model and which explainer artifact produced it. Part 08 stores both with the prediction. |

**Summary sentence.** It is templated from the ranked factors (`summary.py`), so it is deterministic and every word traces to a field:

- A risk prediction reads "The model predicts {Class} conditions ({p} probability), mainly because of {up to 3 factors raising risk}. {Up to 2 lowering factors} partly offset the risk."
- A NORMAL prediction reads "The model predicts Normal conditions ({p} probability). The main factors keeping the risk low are {up to 3}. {Up to 2 raising factors} raised the risk somewhat."
- Only factors carrying ≥ 5 % of the explanation are named. If none qualifies, the sentence says "No single factor stood out."
- Probabilities are whole percentages, but never "100%" or "0%" (`>99%`, `<1%`): the model is never certain.
- Factors are named with their values and **no adjectives**. The first draft said "high maximum temperature (35.5 °C)" for a factor that *lowered* the risk: 35.5 °C is above the annual median, but below the background's heat days. An adjective needs a reference point that the SHAP sign doesn't share, and the result reads as a contradiction.

## 4. Background (reference) data (Part 06 §4)

| | |
|---|---|
| Source | The production model's **own training split** of `data/heatwave_dataset.csv`. The builder refuses a dataset whose SHA-256 differs from the one in the bundle's `training_data`. |
| Size | 100 rows (`SHAP_BACKGROUND_ROWS`) |
| Sampling | Simple random, seeded (`RANDOM_SEED`=42), sorted by `record_id`. Deliberately not stratified: the baseline should be the average *day*, so the training class mix (mostly NORMAL) is kept. |
| Frozen as | `ml/registry/explainers/<model_version>/background.csv` (model inputs + `record_id`, before imputation) with its SHA-256 in `explainer.json` |
| Resulting baseline | `expected_value` per class in the manifest: log(P(SEVERE)/P(NORMAL)) = −5.95 and log(P(HEATWAVE)/P(NORMAL)) = −4.36 for the average background day. |

**Why 100 rows.** Interventional cost is linear in background size. On the 746 validation rows, compared with a 500-row background (≈100 ms/row), the 100-row one (≈21 ms/row) had the same top factor on 97.3 % of rows and the same top-3 set on 91.3 %, and shares differed by 1.8 points on average. A different 100-row sample (seed 7) differed about as much (94.6 % / 90.2 % / 2.6 points), so the choice of sample matters about as much as the size does. Freezing the sample is what makes explanations stable across restarts.

**Found while building:** SHAP's `TreeExplainer` **silently subsamples any background larger than 100 rows** down to 100, which would have made `SHAP_BACKGROUND_ROWS` > 100 both a lie and a source of non-reproducibility. The background is therefore passed as `shap.maskers.Independent(background, max_samples=len(background))`, and a test checks that the baseline is the mean output over *every* background row.

## 5. Feature labels (Part 06 §5)

`config/feature_labels.json` is the single table of user-facing names:

- **Features:** `label`, a short display `unit`, `unit_detail`, display `decimals`, and `signed`, keyed by the internal names of `FEATURE_COLUMNS`.
- **Risk classes:** display names (`SEVERE_HEATWAVE` → "Severe Heatwave"). The enum value itself never changes.

It is JSON so the frontend can import it without a parser (Part 10). `heatwave_ml.features.schema` loads it (`FEATURE_LABELS`, `FEATURE_UNITS`, `FEATURE_DISPLAY`, `RISK_CLASS_LABELS`) and fails at import if its features or classes drift from the schema. The labels and units that Part 03's dataset manifest records are unchanged. The API also returns `label`, `unit` and `display_value` on every factor, so the frontend can render an explanation without the table.

## 6. Performance (Part 06 §6)

`explain()` timed end to end (preprocessing, prediction, SHAP, contract, summary) at build, on 50 distinct training rows, and recorded in the manifest:

| | p50 | p95 |
|---|---|---|
| One row (one live request) | 27.6 ms | 45.4 ms |
| 15 rows (5 regions × 3 forecast days) | 338 ms | — |

The budget in Part 05's policy (`gates.max_p95_request_ms`, prediction plus explanation) is **500 ms**, and the build fails if the p95 exceeds it. The same laptop caveat as Part 05 §3.5 applies (Windows on battery throttles processes several-fold), so Part 07 and Part 18 must re-measure on the serving host. Cost is linear in rows × background size. A scheduled run over all regions and days should explain in one batch call, not row by row. Caching is unnecessary at this scale.

- **Per request:** explanations are computed **per request**. Global importance is recorded separately (§7) and is never served in place of a per-prediction explanation.
- **Speed-ups that don't change results:** SHAP's own per-call additivity check re-predicts every row with a slow Python tree walk, so it is switched off. Additivity is instead checked explicitly by the builder and the tests. Rows are explained in chunks of 50, because SHAP's C extension prints a progress bar on long calls.

## 7. Validation (Part 06 §7)

All of these run in `heatwave-explain build`, which fails and saves nothing if any of them fails, and again in `verify`. They are also permanent tests (Part 17 §2).

**Consistency (SHAP additivity), automated.** Measured on all 746 validation rows:
- **Per class:** max |baseline + Σ SHAP − raw output| = 2.2 × 10⁻⁶ (float32 arithmetic inside XGBoost).
- **Target-vs-NORMAL sum:** max |sum − log(P(t)/P(NORMAL))| = 1.4 × 10⁻⁶ against the model's own probabilities.
- **Agreement:** probabilities are bit-identical to `ModelBundle.predict_proba`.

The tests assert the same property for all three model families (tolerance 10⁻⁴).

**Found while building: Random Forest additivity was off by up to 2.8 × 10⁻⁴.** The cause was traced to one tree whose split threshold (4.00999999 on Temperature Deviation) lies between two adjacent float32 values. scikit-learn compares the float32 input with the float64 threshold. SHAP's interventional code rounds the threshold to the *nearest* float32, which equals one background row's value (4.0100002), so that row went left in SHAP and right in the model. One background row on the wrong branch shifts every explanation by a leaf's weight. The fix was two changes:
- rounding tree-model inputs to float32, as the models do;
- setting RF thresholds to the largest float32 ≤ the original, which reproduces scikit-learn's branching exactly.

RF error is now about 10⁻⁸ for every background seed tried. XGBoost stores float32 thresholds and was never affected.

**Hand-picked sanity cases** (`sanity.py`). Raw weather rows for Mumbai on 15 May, whose seasonal normal is 34.6 °C, are run through `build_features` exactly as live inference runs them. The labelling rule uses only Tmax and its departure from normal, so those must dominate. Wind is not in the rule, but hot spells in the data come with calmer air, so strong wind may only ever lower the risk.

| Case | Input | Result on the production model | Check |
|---|---|---|---|
| extreme_heat | Tmax normal + 8 °C, RH 35 %, wind 1.6 m/s | SEVERE (>99 %). Deviation +65 %, Tmax +33 % | predicted SEVERE; the top two are the temperature features, both raising risk ✔ |
| typical_day | normal + 0.3 °C, RH 70 % | NORMAL (>99 %). Deviation −49 %, Tmax −33 % | NORMAL; deviation lowers risk ✔ |
| cool_day | normal − 3 °C | NORMAL | the top factor is a temperature feature lowering risk ✔ |
| heatwave_calm | normal + 5.5 °C, wind 1.2 m/s | HEATWAVE (>99 %). Wind +0.06 | HEATWAVE or worse, temperature-driven ✔ |
| heatwave_windy | the same day with wind 5.0 m/s | HEATWAVE (99 %). **Wind −0.28 (protective)** | wind lowers risk, and by more than the calm day's wind ✔ |
| heat_missing_humidity | normal + 7 °C, RH missing | SEVERE (88 %). RH filled with the May median, `imputed: true` | still explained; RH flagged ✔ |

Two real validation days, from `heatwave-explain explain`:

- **Andheri, 2001-07-09 (labelled SEVERE):** "The model predicts Severe Heatwave conditions (>99% probability), mainly because of Temperature Deviation (+7.5 °C), Maximum Temperature (37.5 °C) and Seasonal Normal Temperature (30.0 °C)." Deviation +75.4 %, Tmax +16.4 %. It is severe at only 37.5 °C because the coastal zone's minimum is 37 °C and the departure exceeds 6.5 °C, which is exactly the IMD rule.
- **Andheri, 2000-09-21 (labelled HEATWAVE):** "…Heatwave conditions (74% probability), mainly because of Temperature Deviation (+6.2 °C), Maximum Temperature (37.2 °C) and Seasonal Normal Temperature (31.0 °C)." Solar radiation, humidity and wind are small negatives.

**Global importance (dataset-level, not per prediction).** Mean |contribution| over the validation split, stored in the manifest for the analytics page (Part 14):

| Feature | Mean \|contribution\| | Share |
|---|---|---|
| Temperature Deviation | 2.827 | 48.4 % |
| Maximum Temperature | 1.769 | 30.3 % |
| Seasonal Normal Temperature | 0.666 | 11.4 % |
| Relative Humidity | 0.242 | 4.1 % |
| Solar Radiation | 0.200 | 3.4 % |
| Wind Speed | 0.119 | 2.0 % |
| Precipitation | 0.015 | 0.3 % |

**What this means for the UI (a finding, not a defect).** The model has learned the labelling rule: about 90 % of every explanation is temperature. Humidity and wind are real but minor factors. The mockup's "elevated humidity, limited wind dispersion" sentence would overstate them for this model, and the templated summary only names factors with ≥ 5 % of the explanation. If the project later labels with a heat-index-based rule, the same machinery will show humidity rising, with no code change.

## 8. Versioning and lifecycle (Part 06 §8)

```
ml/registry/explainers/<model_version>/
  explainer.json    manifest: model SHA-256, method, background provenance + SHA-256,
                    expected values, a 20-row probe of expected SHAP values, the build's
                    checks, global importance, benchmark, library versions
  background.csv    the frozen background (100 training rows)
```

- **Committed with the registry, not git-ignored.** It is small (24 KB), and a fresh clone gets the exact reference data. The SHAP object is **rebuilt at load, not pickled**: rebuilding from the model and the background is deterministic and fast, and it avoids pickles tied to a SHAP version.
- **Identity:** `explainer_id` = `<model_version>+shap.<first 8 of background SHA-256>`. The build is logged as an `explainer_built` event in `ml/registry/history.jsonl`, which records who built it and whether it replaced an earlier one.
- **Load-time refusals:** `HeatwaveExplainer.load` / `load_production_explainer` refuse
  - an explainer whose `model_sha256` isn't the model being explained ("Stale explainer"), including after a promotion or rollback without a rebuild;
  - a background whose hash changed;
  - an explainer that no longer reproduces its recorded probe values within 10⁻⁵, for example after a SHAP or XGBoost upgrade.
  The backend therefore cannot explain one model's predictions with another model's explainer.
- **`heatwave-registry verify`** now also checks the production explainer, and **`promote` / `rollback`** print the rebuild command. The Part 05 retraining procedure, step 4, is `uv run heatwave-explain build`.
- **Rebuilding.** `build` is idempotent: the same model, dataset, rows and seed report `unchanged`. A build with different inputs needs `--force` and is logged with `replaced: true`.

## 9. Handoff note (Part 06 → Part 07)

> Explainer artifact at: **`ml/registry/explainers/xgboost-20260928T100821Z-0bde51/`** (`explainer_id` `xgboost-20260928T100821Z-0bde51+shap.2154641e`), built against production model **`xgboost-20260928T100821Z-0bde51`** (model SHA-256 `31f5f4c7…21c1aa57`). SHAP 0.52 `TreeExplainer`, interventional, over 100 frozen training rows. Output contract: §3 above. It is one call, `load_production_explainer(registry)` at startup and then `explainer.explain(model_input(build_features(raw, normals)))`, and `.to_dict()` gives risk class, probabilities, confidence, all 7 ranked signed factors with `share_pct` for the bars, and the summary sentence. Feature label mapping at: **`config/feature_labels.json`** (also exported as `heatwave_ml.features.FEATURE_DISPLAY` / `RISK_CLASS_LABELS`). Per-request latency: **p50 27.6 ms / p95 45.4 ms** for prediction plus explanation on the dev laptop (budget 500 ms), and 338 ms for a 15-row batch; re-measure on the serving host. Part 07 can now wire this into `POST /api/predict`: add `heatwave-ml` as a backend dependency, load the explainer at startup (fail startup if it is stale or missing), and return `.to_dict()` unchanged. Part 08 stores `factors` as `prediction_factors` rows plus `model_version` and `explainer_id` on the prediction.
