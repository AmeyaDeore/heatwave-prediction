# Implementation logs

A running, detailed record of what has actually been built, part by part: what exists now, the decisions made, how it was verified, what went differently from the plan, and what is still open. The `Implementation/` plans say what *should* be built. These logs say what *was* built.

## Rule: log every major change

After every major change, write or update a log in this folder **in the same PR/commit series as the change**. A major change is any of these:

- completing (or substantially advancing) a part of the implementation plan
- a model retrain, re-evaluation, promotion or rollback
- a schema, API-contract, config-contract or dependency change that other parts rely on
- a bug fix or incident that changes behaviour or results

File naming:

| Kind | File name | Example |
|---|---|---|
| A plan part | `NN-<plan-file-slug>.md` (one per part; append a dated "Update" section when revisited) | `05-model-evaluation-selection.md` |
| Anything else | `YYYY-MM-DD-<short-slug>.md` | `2026-10-04-retrain-on-imd-2025.md` |

Add every new log to the index below.

## Template

```markdown
# Log NN — <title>

| | |
|---|---|
| Plan | Implementation/NN-....md |
| Status | Complete / In progress (+ what is outstanding) |
| Date(s) | YYYY-MM-DD |
| Branch / commits | `branch` · `abc1234` … |
| Tests | N new, M total passing |

## Summary
## What was built   (files, modules, CLIs, config, data/artifacts)
## Key decisions and why
## Verification     (commands run and their actual results)
## Deviations from the plan and issues found
## Open items / follow-ups
## Handoff          (what the next part can now assume)
```

## Index

| Log | Part | Status | Date | Commits |
|---|---|---|---|---|
| [01-environment-and-repo-setup.md](01-environment-and-repo-setup.md) | 01 Environment & repo setup | Complete (one human dry-run outstanding) | 2026-09-28 | `f9b562f` |
| [02-data-collection-pipeline.md](02-data-collection-pipeline.md) | 02 Data collection pipeline | Complete | 2026-09-28 | `39df378` |
| [03-data-preprocessing-feature-engineering.md](03-data-preprocessing-feature-engineering.md) | 03 Preprocessing & feature engineering | Complete | 2026-09-28/29 | `44d0ca5` |
| [04-model-development-training.md](04-model-development-training.md) | 04 Model development & training | Complete | 2026-09-28/29 | `894364b` |
| [05-model-evaluation-selection.md](05-model-evaluation-selection.md) | 05 Model evaluation & selection | Complete | 2026-09-29 | `fbdf161` `71dd36d` `e5ead11` |
| [06-shap-explainability-integration.md](06-shap-explainability-integration.md) | 06 SHAP explainability integration | Complete | 2026-09-29 | `0d270d9` `c9b5de9` + artifact/docs commit |
| [07-backend-api-architecture.md](07-backend-api-architecture.md) | 07 Backend API architecture | Complete, with persistence / notifications / users as seams for Parts 08, 09, 15 | 2026-09-29 | `5b44e1c` on `part-07/backend-api` |
| [08-database-design.md](08-database-design.md) | 08 Database design (SQLite) | Complete (Response Coordination panel handed to Part 13) | 2026-10-07 | `5b44e1c` on `part-07/backend-api` |
| [09-notification-service.md](09-notification-service.md) | 09 Notification service | Complete (delivery-receipt webhooks deferred to Parts 16/18) | 2026-10-07 | `part-07/backend-api` |

**Running totals after Part 09:** 289 automated tests passing · production model `xgboost-20260928T100821Z-0bde51` · production explainer `xgboost-20260928T100821Z-0bde51+shap.2154641e` · schema version `0002` · notifications: SendGrid/Twilio behind `NOTIFICATIONS_MODE` (mock default), background dispatch with polling · next part: 10 (frontend architecture & design system).
