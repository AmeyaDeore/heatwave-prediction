# Part 06 — SHAP Explainability Integration

**Depends on:** 05 (final selected model)
**Feeds into:** 07 (backend API — exposes this per prediction)
**Owner persona:** ML engineer

## 1. Objective

Integrate SHAP (SHapley Additive exPlanations) into the inference path so that every prediction the system produces is accompanied by a ranked list of the meteorological factors that drove it, with signed contribution values — this is the core differentiator the project brief describes ("the gap between receiving a warning and understanding why").

## 2. Explainer choice, matched to the selected model

- If the production model (from Part 05) is tree-based (Random Forest or XGBoost), use a tree-specific SHAP explainer — these are exact and fast for tree ensembles, which matters because explanations need to be computed per live request, not just offline.
- If the production model is Logistic Regression, use a linear SHAP explainer, which is exact and cheap for linear models.
- Document this choice explicitly tied to whichever model Part 05 actually selected (the brief's own results indicate Random Forest was chosen, which points to a tree explainer).

## 3. What "explanation" means in this system (output contract)

For a single prediction, the explanation output must contain, at minimum:
- The full ranked list (or a documented top-N, e.g., top 3–4 as shown in the UI mockups) of contributing features.
- Each feature's **signed contribution** — positive values push toward higher risk, negative values push toward lower risk (visible in the UI as e.g. Wind Speed showing a negative/protective contribution while Maximum Temperature shows a large positive one).
- Each feature's contribution expressed in a way the frontend can render directly as a proportional bar (i.e., either a raw SHAP value or a normalized percentage — decide one consistent representation and document it, since Part 12's UI shows percentage-style bars).
- A short, human-readable natural-language summary sentence synthesizing the top factors (the UI mockup shows a sentence like "the model predicts high likelihood... because of persistent temperature anomaly, elevated humidity, and limited wind dispersion") — this can be templated from the ranked factor list rather than requiring free-form generation, keeping it deterministic and testable.

## 4. Background/reference data for the explainer

- SHAP explainers (particularly non-tree ones, and even some tree-explainer configurations) need a background/reference dataset to compute contributions relative to. Decide and document what this reference set is — typically a representative sample of the training data from Part 03 — and freeze it alongside the model artifact so explanations are stable and reproducible across restarts of the service, not recomputed against a different reference each time.

## 5. Mapping raw feature names to user-facing labels

- The model's internal feature names (as fixed in Part 04 Section 5) must be mapped to the human-readable labels the frontend displays: "Maximum Temperature," "Relative Humidity," "Temperature Deviation," "Wind Speed," and so on. Maintain this mapping as a single shared lookup table (referenced by both backend and frontend, or at minimum kept in sync deliberately) rather than duplicating label strings in multiple places.

## 6. Performance considerations

- Explanation computation adds latency on top of the raw model prediction — benchmark this per request for the selected explainer type and confirm it's acceptable for a live API call (tree explainers on a small feature set should be fast; if using a slower explainer type, consider precomputing/caching explanations for common input patterns, though this is unlikely to be necessary at this project's scale).
- Explanations must be computed **per individual prediction request**, not just once globally — global feature importance (which features matter most across the whole dataset) is a different, complementary concept and should not be confused with or substituted for per-prediction explanations in the API contract.

## 7. Validation of explanation quality

- Sanity-check explanations against domain intuition on a handful of hand-picked examples: e.g., a record with an extreme positive temperature deviation should show Temperature Deviation and/or Maximum Temperature as the top positive contributor; a record with high wind speed should show wind speed as a negative (risk-reducing) contributor if that matches the underlying heatwave-criteria rule from Part 03.
- Confirm that the signed contributions are internally consistent with the model's own predicted probability (SHAP values should approximately sum, with the baseline, to the model's output for that prediction) — this is a standard SHAP correctness property and is worth an explicit automated check, not just a visual spot-check.

## 8. Non-functional requirements

- The explanation logic must be packaged as a callable step usable by the backend's live prediction endpoint (Part 07) with a single function-like call taking a prepared feature vector and returning the Section 3 contract — it should not require the backend to know SHAP internals.
- Explainer artifact (including its background reference data) must be versioned alongside the model artifact it explains — if the production model is ever replaced (Part 05, Section 6), the explainer must be rebuilt against the new model, not left pointing at a stale one.

## 9. Acceptance criteria / "done"

- [ ] Explainer type selected and justified against the actual production model type.
- [ ] Background/reference dataset frozen and versioned alongside the model.
- [ ] Output contract implemented exactly as Section 3 specifies (ranked factors, signed contributions, consistent representation, template-based summary sentence).
- [ ] Feature-name-to-label mapping created and shared with frontend/backend owners.
- [ ] Per-request latency benchmarked and confirmed acceptable.
- [ ] Sanity checks against hand-picked examples pass and are documented.
- [ ] SHAP-value consistency check (values sum appropriately with model output) implemented as an automated test.

## 10. Handoff note template

> Explainer artifact at: <path>, built against production model version <id>. Output contract: <link/summary>. Feature label mapping at: <path>. Per-request latency: <measured value>. Part 07 can now wire this into the prediction endpoint.
