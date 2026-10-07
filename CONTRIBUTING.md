# Contributing

## Branches

Each branch maps to one part of the plan in `Implementation/`, so each part is reviewed and merged on its own:

```
part-<NN>/<short-slug>          e.g. part-07/prediction-endpoint
fix/<short-slug>                 bug fixes not tied to an in-progress part
chore/<short-slug>               tooling / dependency bumps
```

Keep PRs to one part, or a slice of one. Large parts (07, 10) should land as several PRs.

## Commits — Conventional Commits (lightweight)

```
<type>(<scope>): <summary in imperative mood>
```

- **type:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`
- **scope:** `ml`, `backend`, `frontend`, `data`, `docs`, `deploy`, `config`, or the part number (`p07`)
- Examples: `feat(backend): add /predictions endpoint with SHAP factors`, `chore(config): add SMS provider vars`

Part 18 builds its changelog and versioning from these prefixes.

> **No AI co-author trailers.** Never add Claude (or any AI tool) as a co-author: no `Co-Authored-By:` line and no "Generated with Claude Code" footer in commit messages or PR descriptions. Commits carry the human author only.

## Pull requests

- `main` is protected: at least **1 approving review** and passing checks are required. Nobody pushes to it directly.
- Before opening a PR, run `uv run pre-commit run --all-files` and `uv run pytest`.
- Add any new env variable to the right `.env.example` **and** to the inventory in `docs/configuration-and-secrets.md` in the same PR.
- Keep the shared vocabulary exact: `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`.
- When a PR completes a part, include that part's handoff note in the PR description.

## Setting up branch protection (repo admin, one-time)

On GitHub: Settings → Branches → Add rule for `main`. Enable:
- Require a pull request before merging, with 1 approval
- Require status checks to pass (add the CI checks once Part 18 creates them)
- Do not allow bypassing the above settings
