# Configuration & secrets

## Rules

1. Anything that differs between local, staging and production is an **environment variable**, never a value in code.
2. Each concern has **one template**, committed with placeholder values only:

   | Concern | Template | Local copy (git-ignored) |
   |---------|----------|--------------------------|
   | Backend | `backend/.env.example` | `backend/.env` |
   | ML pipeline | `ml/.env.example` | `ml/.env` |
   | Frontend (build-time, **public**) | `frontend/.env.example` | `frontend/.env.local` |

3. Values that several concerns share conceptually (risk thresholds, monitored regions) live **once** in `config/*.yaml`. Each concern's env file points to that file with a path variable (`RISK_CONFIG_PATH`, `MONITORED_REGIONS_FILE`). The values themselves are never copied.
4. Frontend variables are compiled into the public bundle, so they must never contain secrets.
5. Staging and production values are stored in the hosting platform's secret store (Part 18), never in the repo. Each environment has its **own** credentials, so staging cannot send a real SMS.
6. The `detect-secrets` pre-commit hook blocks commits that contain credential-like strings. If it flags a false positive, audit it with `uv run detect-secrets audit .secrets.baseline` rather than disabling the hook.

## Variable inventory

This is a living list. Parts 02, 07, 09, 15 and 18 add to it, and each new variable goes in the matching `.env.example` in the same PR.

| Variable | Concern | Secret? | Introduced by |
|----------|---------|---------|---------------|
| `APP_ENV`, `LOG_LEVEL` | backend, ml | no | 01 |
| `DATABASE_URL` | backend | yes, once it is Postgres | 08 |
| `DATABASE_BACKUP_DIR` | backend (`heatwave-db backup`) | no | 08 |
| `MODEL_ARTIFACT_DIR`, `MODEL_VERSION` | backend, ml | no | 04/05 |
| `MODEL_REGISTRY_DIR` | backend, ml | no | 05 |
| `MODEL_SELECTION_POLICY` | ml | no | 05 |
| `RISK_CONFIG_PATH` | backend, ml | no | 01/03 |
| `CORS_ALLOWED_ORIGINS` | backend | no | 07 |
| `SEASONAL_NORMALS_FILE`, `ALERT_CHANNELS_FILE`, `RECOMMENDED_ACTIONS_FILE` | backend (+ ml for the normals) | no | 07 |
| `WEATHER_FEATURES_FILE`, `WEATHER_STALE_AFTER_HOURS` | backend | no | 07 |
| `RATE_LIMIT_PREDICT_PER_MINUTE`, `RATE_LIMIT_ALERTS_PER_MINUTE`, `RATE_LIMIT_LOGIN_PER_MINUTE` | backend | no | 07 |
| `DEMO_USER_USERNAME`, `DEMO_USER_PASSWORD` | backend (`local`/`test` only) | **yes** if ever reused; never set in staging or production | 07 |
| `AUTH_SECRET_KEY`, `AUTH_TOKEN_TTL_MINUTES` | backend | **yes** (key). Startup refuses the local default outside `local`/`test` | 07/15 |
| `NOTIFICATIONS_MODE` | backend | no | 09 |
| `EMAIL_PROVIDER`, `EMAIL_API_KEY`, `EMAIL_FROM_ADDRESS` | backend | **yes** (key) | 09 |
| `SMS_PROVIDER`, `SMS_API_KEY`, `SMS_SENDER_ID` | backend | **yes** (key) | 09 |
| `NASA_POWER_BASE_URL` | backend, ml | no (public API) | 02 |
| `RAW_DATA_DIR`, `PROCESSED_DATA_DIR`, `SAMPLE_DATA_DIR` | ml | no | 02/03 |
| `MONITORED_REGIONS_FILE` | ml | no | 02 |
| `OPEN_METEO_FORECAST_URL`, `FORECAST_DAYS` | ml | no (public API) | 02 |
| `IMD_GRIDDED_TMAX_URL`, `IMD_FETCH_MODE`, `IMD_INBOX_DIR`, `IMD_HISTORY_START_YEAR` | ml | no | 02 |
| `NASA_POWER_RECENT_DAYS`, `SYNTHETIC_RECORD_COUNT` | ml | no | 02 |
| `INGEST_HTTP_TIMEOUT_SECONDS`, `INGEST_MAX_ATTEMPTS`, `INGEST_BACKOFF_BASE_SECONDS` | ml | no | 02 |
| `TRAINING_START_DATE`, `TRAINING_END_DATE`, `RANDOM_SEED` | ml | no | 02/03/04 |
| `SEASONAL_NORMALS_FILE` | ml, backend (from Part 07: live features need it) | no | 03 |
| `MODELING_DATASET_PATH`, `TEST_FRACTION`, `VALIDATION_FRACTION` | ml | no | 03 |
| `CV_FOLDS`, `TRAINING_N_JOBS` | ml | no | 04 |
| `VITE_API_BASE_URL`, `VITE_DEFAULT_REGION`, `VITE_DASHBOARD_POLL_INTERVAL_MS` | frontend | no (public) | 10 |

## Secret ownership & rotation

| Secret | Owner | Where issued |
|--------|-------|--------------|
| Email provider API key | Backend lead (Person B) | Provider dashboard (chosen in Part 09) |
| SMS provider API key | Backend lead (Person B) | Provider dashboard (chosen in Part 09) |
| `AUTH_SECRET_KEY` | Backend lead (Person B) | Generated locally per environment |
| Weather data access | Data/ML lead (Person A) | NASA POWER needs no key. IMD data access, if credentialed, belongs to Person A |

**If a secret leaks** (committed, pasted in chat, or exposed in logs):

1. **Revoke first.** The owner disables the key in the provider dashboard immediately. Removing it from git history does *not* make it safe.
2. **Issue a replacement** and update it in each affected environment's secret store and in contributors' local `.env` files.
3. **For `AUTH_SECRET_KEY`:** rotating it invalidates every active session. Everyone must log in again, which is expected.
4. **Clean up:** if the leak was a commit, rewrite history only if the branch was never pushed. Otherwise rely on revocation.
5. **Record it:** add a short note to `docs/decisions/` covering what leaked, when, and the time to revoke.

**Scheduled rotation:** rotate provider keys at least once per term/semester and whenever a team member with access leaves.
