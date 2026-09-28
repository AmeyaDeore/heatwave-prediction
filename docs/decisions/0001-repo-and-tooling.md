# ADR 0001 — Repository layout and tooling

**Status:** Accepted, 2026-09-28 (Part 01)

## Decisions

| Area | Choice | Why |
|------|--------|-----|
| Repo strategy | Monorepo: `data/ ml/ backend/ frontend/ docs/ deploy/ tests/ config/` | A 3-person team with shared contracts (risk classes, API shape). One PR can change a contract on both sides at once. |
| Shared config | `config/` at root for non-secret values that more than one concern reads | Implements "define once, reference". Added to the Part 01 layout. |
| Python | 3.13, one version for `ml/` and `backend/` | The model pickle must load with the same interpreter and library versions it was trained with. |
| Python deps | uv workspace, single `uv.lock` at root | One lock means serving uses exactly the scikit-learn, XGBoost and SHAP versions used in training. `--package` still lets each side install alone. |
| Python format + lint | Ruff (`ruff format`, `ruff check`) | A single fast tool that replaces black, isort and flake8. |
| JS runtime / deps | Node 22 LTS, npm, `package-lock.json` | Ships with Node, so there is nothing extra to install. |
| JS format + lint | Prettier and ESLint (flat config) | The standard pair. Part 10 adds framework plugins. |
| Frontend framework | **Deferred to Part 10** | Part 10 owns the stack choice. Env var names assume Vite (`VITE_` prefix) provisionally. |
| Secret scanning | detect-secrets via pre-commit, with a `.secrets.baseline` | Pure Python, installed through uv, works on Windows without a Go toolchain. |
| Pre-commit | `pre-commit` framework. Python hooks run via `uv run`. | Tool versions come from `uv.lock`, so they can't drift from a second pin. |
| Line endings | LF everywhere (`.gitattributes`, `.editorconfig`) | Mixed Windows and Unix contributors. Avoids whole-file diffs. |

## Consequences

- `Implementation/` (the plan set) stays at the repo root for now because existing workflows reference it by that path. `docs/README.md` points to it.
- Heavy ML dependencies are in `heatwave-ml`, not `heatwave-api`. When Part 07 loads the model artifact, the backend must add the inference-time subset (scikit-learn, xgboost, shap) as its own dependencies. The shared lock keeps the versions identical.
