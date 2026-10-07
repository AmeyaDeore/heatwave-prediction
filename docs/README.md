# docs/

| Document | Purpose |
|----------|---------|
| [local-dev-runbook.md](local-dev-runbook.md) | Clean checkout → running system |
| [configuration-and-secrets.md](configuration-and-secrets.md) | Env var strategy, variable inventory, secret rotation |
| [decisions/](decisions/) | Architecture decision records (ADRs) |
| [data/raw-landing-zone.md](data/raw-landing-zone.md) | Part 02 ingestion: adapters, raw layout, schema, run log, scheduling |
| [data/field-availability.md](data/field-availability.md) | Which source supplies which field, measured gaps, handoff to Part 03 |
| [data/heatwave-labeling-spec.md](data/heatwave-labeling-spec.md) | Part 03: the versioned NORMAL / HEATWAVE / SEVERE_HEATWAVE rule |
| [data/synthetic-dataset.md](data/synthetic-dataset.md) | Part 03: how the 5,000-record synthetic set is generated and why |
| [data/preprocessing.md](data/preprocessing.md) | Part 03: cleaning decisions, features, train/inference parity, split, handoff to Part 04 |
| [ml/training.md](ml/training.md) | Part 04: training pipeline, search spaces, imbalance strategy, artifact bundle contract, experiment log, results, handoff to Part 05 |
| [ml/evaluation.md](ml/evaluation.md) | Part 05: selection policy, test-split results and comparison table, justification, production pointer and registry, retraining and rollback, handoff to Part 06 |
| [ml/explainability.md](ml/explainability.md) | Part 06: SHAP explainer, the per-prediction explanation contract, frozen background, label table, validation (additivity + sanity cases), versioning, handoff to Part 07 |
| [api/README.md](api/README.md) | Part 07: the `/api/v1` contract (envelope, errors, auth, every endpoint), weather-source decision, model lifecycle, limits, handoff to Parts 08-10 |
| [database/README.md](database/README.md) | Part 08: SQLite schema (tables, constraints, ER diagram), indexes, UI cross-check, retention and backups, migrations, PostgreSQL path |
| [logs/](logs/) | Detailed implementation log per completed part / major change (what was built, decisions, verification, open items). **Update after every major change.** |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Branching, commit and PR conventions |
| [../Implementation/](../Implementation/) | The 18-part implementation plan set (start with `00-README-master-plan.md`) |

Architecture diagrams are added here by Part 16.
