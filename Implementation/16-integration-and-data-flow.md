# Part 16 — End-to-End Integration & Data Flow

**Depends on:** all prior parts (02–15)
**Feeds into:** 17 (testing), 18 (deployment)
**Owner persona:** Whole team, coordinated by whoever owns backend/architecture

## 1. Objective

This part exists because building each piece correctly in isolation does not guarantee the whole system works together. Its job is to verify and wire together the full path shown in the original architecture diagram, end to end, and to catch integration gaps between the parts built independently in Parts 02–15.

## 2. The full path to verify (matching the architecture diagram exactly)

1. Weather Data Sources (IMD / NASA POWER / Dataset) →
2. Data Preprocessing & Feature Engineering →
3. Machine Learning Models →
4. Heatwave Prediction (Risk + Probability) →
5. SHAP Explainability →
6. Backend API ↔ Database →
7. Notification Service →
8. Web Dashboard →
9. Local Authority / Disaster Management Official (the end user, closing the loop by taking action)

Integration work means proving this chain functions as one system, not nine independent demos.

## 3. Integration checkpoints (each is a concrete, testable milestone)

### 3.1 Data → Model checkpoint
- Confirm the exact feature computation used in Part 03 (training-time) is the same module invoked by Part 07's live prediction path — not a re-implementation. This was flagged as a risk in Part 03 Section 6; this is where it gets formally verified, e.g., by feeding one known historical record through both the training pipeline's feature computation and the live API's feature computation and confirming identical output.

### 3.2 Model → API checkpoint
- Confirm the backend loads the exact production model artifact and explainer selected in Parts 05–06 (matching version identifiers), not a stale or default one.
- Confirm the API's response contract (Part 07 Section 3.1) is fully populated end-to-end: risk class, probability, raw inputs, ranked SHAP factors, and recommended actions all present and correctly sourced — not partially mocked.

### 3.3 API → Database checkpoint
- Confirm every prediction served is actually persisted (Part 08's `predictions` and `prediction_factors` tables) and that the analytics page's historical charts (Part 14) reflect real accumulated data over time, not just the single latest prediction.
- Confirm alert creation, status transitions (draft → issued), and channel delivery status updates round-trip correctly between Part 07's endpoints and Part 08's schema.

### 3.4 API → Notification checkpoint
- Confirm issuing an alert through the real Alerts page (Part 13) triggers real dispatch attempts through Part 09's service (using mock/sandbox provider credentials in this environment) and that delivery status changes are visible back on the Alerts page without a manual page reload beyond the defined polling interval.

### 3.5 API → Frontend checkpoint (all four pages)
- Confirm each of Parts 11–14 is reading from the real backend (Part 07) rather than any placeholder/mock data left over from earlier independent development, and that switching the selected region correctly updates every page that depends on it.
- Confirm number consistency across pages: the risk class and probability shown on the Dashboard's condensed view for a region matches exactly what the Prediction page shows for that same region at that same point in time (a common integration bug is two pages independently formatting/rounding the same underlying number differently).

### 3.6 Auth checkpoint
- Confirm the full login → session → protected-action (issue alert) → logout flow works through the real frontend and backend together, including the session-expiry handling defined in Part 15.

## 4. Known integration risk areas to pay special attention to (called out from earlier parts)

- Feature parity between training and inference (Part 03 Section 6 / this file Section 3.1) — the single highest-risk seam in the whole system, since a silent mismatch here would produce a working-looking but subtly wrong model in production.
- The Response Coordination vs. Alert Distribution data-source ambiguity flagged in Part 13 Section 2.5 — resolve this concretely during integration if it wasn't already settled.
- Whether `GET /api/predict`-equivalent data can be served as one composite call for the dashboard (flagged in Part 11 Section 4) versus requiring multiple frontend calls — resolve any resulting backend contract gaps now.
- Model version consistency across the Analytics page's Model Performance panel (Part 14 Section 2.5), the backend's loaded model (Part 07 Section 5), and the actual production pointer (Part 05 Section 5) — all three must agree at all times.

## 5. Integration environment

- Stand up one shared environment (distinct from each developer's local setup) where the real backend, real database, real (or sandboxed) notification providers, and real frontend build all run together against the same data — this is where the checkpoints in Section 3 are actually exercised, since purely local development with mocked pieces cannot catch these issues.
- Seed this environment with a realistic slice of data (a run of the real or synthetic pipeline through several regions and a few historical days) so the Analytics and Dashboard pages have something meaningful to show, not empty states, during integration testing.

## 6. Non-functional requirements

- No part should be considered "done" per its own file's acceptance criteria until it has also passed its relevant checkpoint(s) in Section 3 — individual-part acceptance criteria are necessary but not sufficient.
- Integration issues found here should be logged and routed back to the owning part's plan file for a fix, keeping each part's documentation the authoritative record of what it actually does.

## 7. Acceptance criteria / "done"

- [ ] All six checkpoints in Section 3 verified in the shared integration environment.
- [ ] All four known risk areas in Section 4 explicitly resolved and documented.
- [ ] Cross-page number consistency spot-checked for at least one full prediction across Dashboard, Prediction, and Analytics pages.
- [ ] Full login-to-alert-issuance-to-notification flow demonstrated end-to-end by someone other than the original implementer.

## 8. Handoff note template

> Integration environment at: <location>. Checkpoints passed: <list>. Issues found and routed back: <list with owning part references>. System is ready for Part 17's formal test suite to be run against it.
