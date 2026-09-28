# frontend/

Web dashboard for Local Authority / Disaster Management Officials (Parts 10–14).

**Status:** tooling only. Prettier, ESLint and the npm lock file are set up. The framework, router and design system are chosen in Part 10.

```sh
npm ci                # install exactly what package-lock.json pins
npm run lint
npm run format:check
```

Config: copy `.env.example` to `.env.local`. That file is git-ignored and must contain no secrets, because everything in it ends up in the bundle.
