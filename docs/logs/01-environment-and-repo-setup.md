# Log 01 — Environment and repository setup

| | |
|---|---|
| Plan | [Implementation/01-environment-and-repo-setup.md](../../Implementation/01-environment-and-repo-setup.md) |
| Status | Complete, except one item: a **human second-contributor dry run** of the runbook is still outstanding |
| Date | 2026-09-28 |
| Branch / commits | `main` · `f9b562f` feat(setup): initialize repo layout, workspace tooling, and environment |
| Tests | 2 (backend health check, ML package import) |

## Summary

Set up the monorepo skeleton that every later part builds on: one repository holding data, ML, backend, frontend, docs and deployment, with pinned runtimes, a single Python lock file shared by the ML pipeline and the backend, linters/formatters, secret scanning, environment templates and a local-dev runbook.

## What was built

**Layout** (ADR 0001):

```
data/        raw/ processed/ local/ (git-ignored contents) · sample/ (committed)
ml/          heatwave-ml package (src/heatwave_ml), tests, artifacts/ (git-ignored)
backend/     heatwave-api package: FastAPI app (main.py, /health), Settings (config.py), tests
frontend/    Node 22 project: ESLint (flat config) + Prettier; framework deferred to Part 10
config/      shared, non-secret config: regions.yaml, risk_classes.yaml
docs/        runbook, configuration & secrets, decisions/ (ADRs)
deploy/ tests/   placeholders with READMEs
Implementation/  the 18-part plan set (kept at root; referenced by path)
```

**Tooling and pins**

| Area | What |
|---|---|
| Python | 3.13 (`.python-version`, `requires-python`) for both `ml/` and `backend/` |
| Dependencies | uv workspace (`pyproject.toml` at root, members `ml`, `backend`), **one `uv.lock`**, so the backend unpickles models with the exact library versions used in training |
| Node | 22 LTS (`.nvmrc`, `engines`), npm with `package-lock.json` |
| Python lint/format | Ruff (`line-length 100`, rules E/W/F/I/B/UP/SIM) |
| JS lint/format | ESLint flat config + Prettier |
| Git hooks | `.pre-commit-config.yaml`: merge-conflict, YAML/TOML, EOF, whitespace, large files, private keys, **detect-secrets** (with `.secrets.baseline`), ruff check/format, prettier, eslint |
| Line endings | `.gitattributes` (`* text=auto eol=lf`) + `.editorconfig` |

**Configuration**

- Three env templates: `backend/.env.example`, `ml/.env.example`, `frontend/.env.example` (frontend vars are public, `VITE_` prefix).
- Shared values live once in `config/`: `risk_classes.yaml` (the `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE` vocabulary and IMD thresholds) and `regions.yaml` (5 Mumbai regions: Mumbai, Kurla, Andheri, Dharavi, Colaba; all in the `coastal` zone).
- Backend `Settings` (pydantic-settings) resolves relative paths against the repo root.

**Docs:** `docs/local-dev-runbook.md` (clone → running system), `docs/configuration-and-secrets.md` (rules, variable inventory, secret ownership and rotation), `CONTRIBUTING.md` (branch naming `part-NN/<slug>`, Conventional Commits, PR rules), `.github/pull_request_template.md`, ADR `docs/decisions/0001-repo-and-tooling.md`.

## Key decisions and why

- **Monorepo:** a 3-person team with shared contracts (risk classes, API shape) can change both sides in one PR.
- **One Python version and one lock for ML + backend:** a pickled model only loads safely with the versions that wrote it.
- **detect-secrets through uv:** pure Python, works on Windows, versions pinned by the lock.
- **Frontend framework deferred to Part 10:** Part 10 owns that choice; env names assume Vite provisionally.

## Verification

2026-09-28: `ruff check`, `ruff format --check`, `eslint`, `prettier --check`, `pytest` and `pre-commit run --all-files` all passed. `detect-secrets` blocked a deliberately planted credential. An automated clean-checkout dry run of the runbook passed.

## Deviations from the plan and issues found

- Added a root `config/` directory (not in the plan's layout) to hold values shared by ML and backend.
- `Implementation/` stayed at the repo root rather than moving under `docs/`, because existing workflows reference that path.

## Open items / follow-ups

- **Human dry run of the runbook by a second contributor** (record it in the runbook's validation log). Steps 7–8 can only be checked once Parts 07 and 10 exist.
- The backend has no ML dependencies yet. Part 07 must add the inference subset (scikit-learn, xgboost, shap); the shared lock keeps versions identical.
- No remote repository has been pushed yet.

## Handoff

Anyone starting Part 02 or Part 07 can assume a working skeleton with agreed tooling, env templates and the shared `config/` files.
