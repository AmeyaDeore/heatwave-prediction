# Part 17 — Testing Strategy

**Depends on:** 16 (integration must exist to be tested against), though unit tests within each part should be written alongside that part, not deferred to here
**Feeds into:** 18 (deployment — tests gate releases)
**Owner persona:** Whole team

> **Revision 2 (2026-10-20, examiner feedback):** adds the `server/` (Node.js + MongoDB) test layers, ports the notification test cases, and adds E2E coverage of login, the Maharashtra map and model-suggested alerts. The Python ML and service suites stay. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

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

*Status checked against the code on 2026-10-20. Part 17 has not started as a part, but unit tests were written alongside Parts 02–10, as §2.1 asks.*

- [ ] Unit tests exist for every part listed in Section 2.1, each written by that part's owner. *(**Partly.** They exist for Parts 02–06 (`ml/tests/`), 07–09 (`backend/tests/`) and 10 (`frontend/`, 145 tests), plus the R2 `server/` skeleton (37). Missing for Parts 11–15, which are not built.)*
- [ ] Integration tests automate the Part 16 checkpoints, including the feature-parity regression test specifically. *(A train-vs-forecast feature-parity test exists in `ml/tests/test_features.py`; the other checkpoints await Part 16.)*
- [ ] A focused E2E suite covers the critical login-to-alert-issuance journey. *(Not started.)*
- [ ] A model-quality regression test enforces a minimum metric floor against a frozen test set. *(Not started as a test. The Part 05 policy gates and `heatwave-evaluate verify` re-derive the metrics, but no automated floor test runs in the suite.)*
- [x] Explanation sanity checks are captured as permanent automated tests. *(Part 06: `heatwave_ml.explainability.sanity` cases, run in `ml/tests/test_explainability.py` and at explainer build/verify.)*
- [ ] Test data strategy (Section 3) implemented — no automated test depends on a live external provider. *(**Partly.** No existing test calls a live provider: fakes for HTTP ingestion, mock notification mode, an in-memory MongoDB for `server/`. The seeded E2E/integration database of §3 does not exist yet.)*
- [ ] Full suite runs as part of the pre-merge process defined in Part 01. *(Not yet: pre-commit runs formatters, linters and the secret scan, not the test suites; there is no CI workflow.)*

## 6. Handoff note template

> Test suite locations: <paths, per layer>. Current pass/fail status: <summary>. Minimum model-quality threshold enforced: <value>. System is ready for Part 18's deployment pipeline to gate releases on this suite.

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** ⏳ **Not started** (step 11).

### R2.1 New and changed test layers
| Layer | Location | What | Tooling |
|---|---|---|---|
| Node unit | `server/` | validation schemas, auth (hash, JWT, revocation, lockout), draft-suggestion rule, template rendering and SMS truncation, retry classification | Vitest |
| Node API integration | `server/` | every endpoint in Part 07 §B against an **in-memory MongoDB** and a **fake ML service**: envelope, taxonomy, auth matrix (Part 15 R2.2), idempotency, rate limits, `ML_SERVICE_UNAVAILABLE` | Vitest + HTTP-level requests + in-memory MongoDB |
| Contract | `server/`, `frontend/` | Node responses validate against `docs/api/openapi.json` (generated); the frontend's `contract.test.ts` checks its fixtures against the same file | existing + new |
| Notification parity | `server/` | every scenario from `backend/tests/test_notifications.py`, ported (Part 09 R2) | Vitest |
| MongoDB | `server/` | validators reject bad enums and missing fields; unique and TTL indexes; query plans for latest-by-region and analytics use the indexes | in-memory MongoDB |
| ML service | `backend/`, `ml/` | existing pytest suites, plus `SERVICE_ROLE=ml`, the service token, `/predict/batch`, `/model` | pytest (existing) |
| Frontend | `frontend/` | login page and guard, `MaharashtraMap` (colour, label and shape per class, keyboard selection, table equivalent), suggested-drafts list | Vitest + Testing Library (existing) |
| E2E | `tests/` | login → map → select place → drill into prediction → open suggested draft → issue → statuses update → logout; anonymous access redirects to login | browser automation against the three services + MongoDB, mock providers |

### R2.2 Model quality
The model-quality floor (§2.4) is enforced **per zone** (coastal and plains) on the frozen v2 test split, including the SEVERE → NORMAL = 0 gate per zone (Part 05 R2). Inland sanity cases are added to the explanation tests (Part 06 R2).

### R2.3 Test data
- A fixed seed set: places from `regions.yaml`, a handful of stored predictions per class and zone, one official user, alerts in DRAFT / suggested / ISSUED states. It is loaded into the in-memory MongoDB for integration tests and into the E2E database.
- No automated test uses a real MongoDB server, real providers or live weather APIs (§3, unchanged).

### R2 acceptance criteria
- [ ] Every layer in R2.1 exists and runs in the pre-merge check.
- [ ] Notification parity suite complete and green.
- [ ] Per-zone model-quality floor enforced.
- [ ] The E2E journey in R2.1 passes against mock providers.
- [ ] Root-level test command runs the Python, server and frontend suites together.
