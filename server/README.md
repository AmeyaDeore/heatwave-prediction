# server/

The Node.js + Express application API on MongoDB (Revision 2: master plan §2.1, [ADR 0010](../docs/decisions/0010-mern-application-layer.md)). It will serve the `/api/v1` contract in [`docs/api/README.md`](../docs/api/README.md) to the React frontend and call the FastAPI service (`backend/`) for predictions.

**Status: Revision 2 steps 1 and 4.** It runs on MongoDB and calls the FastAPI ML service (`SERVICE_ROLE=ml`) for every prediction. It serves places, weather, predictions (single, batch, latest, latest-by-region, by id) and readiness. Login and the frontend switch (step 5), alerts (step 8) and analytics (step 9) are not built yet. **The frontend still uses the FastAPI `app` role** until step 5, and until then these routes are open, as the FastAPI reads are today.

```sh
npm ci                     # Node 22 (../.nvmrc)
cp .env.example .env       # optional: the defaults are the local values
npm run db:check           # is MongoDB reachable? read-only
npm run dev                # http://localhost:4000, restarts on change
npm test                   # in-memory MongoDB, never your local one
npm run typecheck && npm run lint && npm run format:check
npm run build && npm start # compiled output in dist/
npm run db:migrate         # apply MongoDB migrations (staging/production: after mongodump); --status only reports
npm run score-all          # score every place x lead 0-3 through the ML service; --only-missing
```

Needs the ML service running: from the repo root, `SERVICE_ROLE=ml ML_SERVICE_TOKEN=<same as server/.env> uv run uvicorn heatwave_api.main:app --port 8000`.

| Endpoint                                                        | Purpose                                                                                                                                                                                |
| --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /health`                                                   | liveness: `{"status":"ok","env":"local"}`, same as the FastAPI service                                                                                                                 |
| `GET /api/v1/regions`                                           | our proposed Maharashtra places, from `config/regions.yaml`                                                                                                                            |
| `GET /api/v1/weather?region_id=&lead_days=`                     | conditions from the ML service, kept as `weather_snapshots`                                                                                                                            |
| `POST /api/v1/predict`                                          | `{region_id, lead_days}` → the ML service's prediction, stored, returned unchanged (rate limited)                                                                                      |
| `POST /api/v1/predictions/batch`                                | `{region_ids?, lead_days?, only_missing?}` → `{scored, skipped, predictions}` (rate limited)                                                                                           |
| `GET /api/v1/predictions/latest?region_id=&lead_days=`          | newest stored prediction (404 if none)                                                                                                                                                 |
| `GET /api/v1/predictions/latest-by-region?lead_days=&division=` | `{items, missing_region_ids}`: the map/table snapshot in one call                                                                                                                      |
| `GET /api/v1/predictions/{id}`                                  | one stored prediction                                                                                                                                                                  |
| `GET /api/v1/health/ready`                                      | readiness: `{ready, database, ml_service, model_version, weather_data}`, **503** unless MongoDB and the ML service are both up. Stored reads keep working while the ML service is down |

## Layout

| Path                  | Role                                                                                                                                           |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/main.ts`         | entry point: config → logger → database → HTTP, graceful shutdown                                                                              |
| `src/app.ts`          | `createApp({config, database, logger})`, routes, 404 and error handler                                                                         |
| `src/config.ts`       | env parsing and validation (zod); placeholder secrets refused outside local/test; errors name the variable, never the value                    |
| `src/db.ts`           | MongoDB connection (Mongoose), ping and read-only server info. A database that is down does not stop startup; readiness reports it and retries |
| `src/http/`           | the response envelope and `ApiError`; request id + access log                                                                                  |
| `src/logger.ts`       | one JSON object per line on stderr, the FastAPI log shape                                                                                      |
| `src/cli/db-check.ts` | `npm run db:check`                                                                                                                             |
| `src/test/mongo.ts`   | throwaway MongoDB 7.0 for tests (mongodb-memory-server)                                                                                        |

## Dependencies (Part 01 R2.2 budget)

Runtime: `express`, `mongoose`, `zod`. The later budget items (`jsonwebtoken`, `bcryptjs`, `js-yaml`, `cors`) are added in the step that first uses them. Dev: TypeScript, tsx, Vitest, supertest, mongodb-memory-server, ESLint, Prettier, at the same majors as `frontend/`.

The first `npm test` downloads a MongoDB 7.0.14 binary (about 70 MB) into `~/.cache/mongodb-binaries`. Later runs use the cache. Offline machines can point `MONGOMS_SYSTEM_BINARY` at a local `mongod` 7.0.
