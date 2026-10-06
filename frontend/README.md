# frontend/

Web dashboard for Local Authority / Disaster Management Officials (Parts 10–14).

**Status:** tooling only. Prettier, ESLint and the npm lock file are set up. The framework, router and design system are chosen in Part 10.

```sh
npm ci                # install exactly what package-lock.json pins
npm run lint
npm run format:check
```

The backend contract is [`docs/api/README.md`](../docs/api/README.md) (OpenAPI: [`docs/api/openapi.json`](../docs/api/openapi.json)). Every response is `{status, data, error, meta}`. Show `meta.warnings`, and branch on `error.code`.

Feature and risk-class display names come from [`../config/feature_labels.json`](../config/feature_labels.json) (Part 06 §5), the same table the backend and ML code use. Import it; don't copy the strings. The SHAP factor bars consume `share_pct` and `direction` from the API unchanged ([`docs/ml/explainability.md`](../docs/ml/explainability.md) §3).

Config: copy `.env.example` to `.env.local`. That file is git-ignored and must contain no secrets, because everything in it ends up in the bundle.
