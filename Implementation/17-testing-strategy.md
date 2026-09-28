# Part 17 — Testing Strategy

**Depends on:** 16 (integration must exist to be tested against), though unit tests within each part should be written alongside that part, not deferred to here
**Feeds into:** 18 (deployment — tests gate releases)
**Owner persona:** Whole team

## 1. Objective

Define a complete, layered test strategy covering the ML pipeline and the full-stack application, so the system's correctness is verified automatically rather than only by manual spot-checking, and so future changes (e.g., a model retrain) can be validated quickly with confidence.

## 2. Test layers

### 2.1 Unit tests (owned by each part, written during that part's implementation, not after)
- **Part 03 (preprocessing):** each cleaning rule and feature computation (especially Temperature Deviation) tested against known input/output pairs, including edge cases (missing values, boundary threshold values for the heatwave classification rule).
- **Part 04/05 (model):** tests confirming the model artifact loads correctly, produces output in the expected shape/range (valid class, probability between 0 and 1), and that the class label mapping is correctly applied.
- **Part 06 (SHAP):** the consistency check defined in Part 06 Section 7 (SHAP values sum appropriately with model output) implemented as an automated test, plus tests confirming the output contract's shape (ranked list, signed values) is always produced correctly.
- **Part 07 (backend):** per-endpoint tests covering valid input, invalid input, and each documented error case from Part 07 Section 6, using a mocked database and mocked model/explainer so these tests run fast and independent of the real ML artifacts.
- **Part 08 (database):** tests confirming schema constraints (foreign keys, required fields) are enforced, and that key queries (latest-prediction-per-region, historical aggregations) return correct results against known seed data.
- **Part 09 (notifications):** tests using a mock provider confirming dispatch, retry, and status-write-back logic behave correctly, including the "one channel fails, others still succeed" case explicitly required in Part 09 Section 5.
- **Part 10–14 (frontend):** component-level tests for shared components (Risk Badge, Metric Card, Contributing-Factor Bar rendering both positive and negative values correctly) and page-level tests confirming each page renders correctly given a mocked API response matching Part 07's documented contract.
- **Part 15 (auth):** tests for login success/failure, token expiry handling, and that protected endpoints correctly reject unauthenticated requests.

### 2.2 Integration tests
- Automate the checkpoints defined in Part 16 Section 3 as repeatable test suites where feasible (e.g., a scripted test that calls the real prediction endpoint against a test database and asserts a fully-populated response, rather than only manually verifying this once during integration).
- A specific automated integration test for the feature-parity checkpoint (Part 16 Section 3.1 / Part 03 Section 6) — this is important enough to be a permanent regression test, not a one-time manual check, since a future change to either the training pipeline or the inference path could silently reintroduce a mismatch.

### 2.3 End-to-end (E2E) tests
- Scripted browser-level tests covering the critical user journeys: log in → view dashboard → drill into a prediction → issue an alert → confirm alert appears with correct initial status → (in a test environment with mock notification providers) confirm delivery status updates appear.
- Keep the E2E suite focused on a small number of critical paths rather than exhaustively covering every UI permutation — unit and integration tests are cheaper and should carry most of the coverage burden.

### 2.4 Model-quality tests (distinct from unit tests — these validate ML behavior, not just code correctness)
- A regression test that re-runs Part 05's evaluation metrics against a fixed, frozen test set and asserts the production model still meets a minimum acceptable threshold (e.g., F1-score above an agreed floor) — this protects against an accidental model swap or artifact corruption silently degrading quality.
- The hand-picked-example sanity checks from Part 06 Section 7 (explanations matching domain intuition) should also be captured as a small, permanent automated test set, not just a one-time manual review.

## 3. Test data strategy

- Use a small, fixed, version-controlled sample dataset (distinct from the full synthetic 5,000-record training set) for fast unit/integration tests — large datasets slow down the test suite and aren't necessary for correctness testing.
- Seed the integration/E2E test database with deterministic known data (specific regions, specific historical predictions, specific alert states) so test assertions can check exact expected values, not just "some data exists."
- Never run automated tests against real external providers (IMD/NASA POWER live APIs, real email/SMS providers) — always use the mock modes defined in Parts 02 and 09 for automated testing, reserving real-provider checks for manual/staging verification only.

## 4. Non-functional requirements

- The full unit + integration test suite should run fast enough to be run on every code change (part of the pre-merge check from Part 01's tooling decisions) — if any layer becomes too slow for this, split it into a fast "always run" tier and a slower "run before release" tier.
- Test failures must be diagnosable without needing to reproduce the full integration environment for every failure — unit tests in particular should fail with a clear, specific message pointing at the exact broken behavior.

## 5. Acceptance criteria / "done"

- [ ] Unit tests exist for every part listed in Section 2.1, each written by that part's owner.
- [ ] Integration tests automate the Part 16 checkpoints, including the feature-parity regression test specifically.
- [ ] A focused E2E suite covers the critical login-to-alert-issuance journey.
- [ ] A model-quality regression test enforces a minimum metric floor against a frozen test set.
- [ ] Explanation sanity checks are captured as permanent automated tests.
- [ ] Test data strategy (Section 3) implemented — no automated test depends on a live external provider.
- [ ] Full suite runs as part of the pre-merge process defined in Part 01.

## 6. Handoff note template

> Test suite locations: <paths, per layer>. Current pass/fail status: <summary>. Minimum model-quality threshold enforced: <value>. System is ready for Part 18's deployment pipeline to gate releases on this suite.
