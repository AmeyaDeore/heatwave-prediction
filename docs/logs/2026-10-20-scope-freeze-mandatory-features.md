# Log: scope freeze, all five mandatory features built and demonstrated

| | |
|---|---|
| Plan | Master plan §4.0/§4.1 (Revision 2), Parts 09, 11, 12, 13, 14 R2 |
| Status | All five mandatory features (M1–M5) work end to end. Steps 10 (retrain) and 11 (integration suite, CI, deployment) not done |
| Date | 2026-10-20 |
| Branch | `part-10/frontend-architecture` (uncommitted, no git operations performed) |
| Tests | server 150 (+16 alerts/analysis), frontend 174 (+16 map/dashboard), Python 337 (+3 skipped, 6 pre-existing errors in `test_production_model.py`) |

## Scope decision (owner, 2026-10-20)
Freeze the scope and keep basic MERN: React + one Node/Express API + MongoDB, with FastAPI only as the ML inference service that Node calls. Finish only the mandatory features; no optional features or polish.

## Mandatory features: where they stand
| | Feature | Built | Evidence |
|---|---|---|---|
| M1 | User login | Node + MongoDB, login required everywhere, logout revokes | `server/src/auth.test.ts`; demo step 1 |
| M2 | MongoDB | 9 migrations: places, predictions, weather_snapshots, model_metadata, users, revoked_tokens, observed_history, alerts, counters | `server/src/db/migrations.ts` |
| M3 | Analysis of Maharashtra places | `/analytics/place`, `/analytics/places`, `/analytics/model` + Analytics page | demo step 5 (Chandrapur: 93 observed heatwave days, hottest 46.9 °C on 22 May 2015) |
| M4 | Maharashtra map | dashboard map (Natural Earth outline, 18 places) | demo step 2 |
| M5 | Node + MongoDB alerts | `/alerts`, `/alert-channels` + Alerts page | demo steps 6–7 (HW-2026-0002, 5/5 channels) |

## What was built in this round
- `heatwave-prepare observed` also writes `data/processed/observed_dataset.csv`, which `npm run import-history` loads into MongoDB `observed_history` (164,376 real place-days, 2000–2024, 18 places; labels from the Python rule, never relabelled).
- `server/src/services/alerts.ts` (+ routes): the FastAPI `AlertOut` contract, `HW-<year>-<seq>` ids via `counters`, idempotent create, issued alerts immutable (409), background **mock** delivery PENDING → NOTIFIED, resume after restart.
- `server/src/services/analytics.ts` (+ routes): per-year heatwave/severe days with an OLS trend (≥10 years), month pattern, records, longest spell, stored-prediction counts per lead, place comparison, shared-IMD-cell detection from the data.
- Frontend: `prediction-page.tsx`, `analytics-page.tsx`, `alerts-page.tsx` (replacing the placeholders); `formatHistoricDate`.

## End-to-end demo (real browser, real stack, 2026-10-20)
Node API + FastAPI (`SERVICE_ROLE=ml`, scratch-registry model) + MongoDB 7.0.31 + Vite:
```
1 login → /                                  (signed out first; /login → dashboard)
2 Maharashtra map: 18 place markers
3 map click → Chandrapur; risk card: NORMAL, valid Tue 20 Oct
4 prediction: NORMAL, Chandrapur today, inland caveat shown, 7 SHAP factors
5 analysis: 93 heatwave days observed 2000–2024; hottest 46.9 °C; comparison top: Chandrapur 3.72/yr
6 Warning HW-2026-0002 issued (confirmation step)
7 5 of 5 channels notified. Mock delivery: recorded only, no real SMS or e-mail was sent.
console errors: none
```
**Blocker found and fixed:** historical dates on the Analytics page showed no year ("Fri, 22 May"). They now read "22 May 2015".

## Limitations (stated in the UI and here)
- **Model not validated for inland places:** the production model was trained on coastal Mumbai synthetic data (step 10 not done). Every inland prediction carries the caveat (`VITE_INLAND_MODEL_VALIDATED=false`).
- **This machine runs a locally trained model** from a scratch registry (Apple Silicon cannot reproduce the committed bundle). Its metrics (macro-F1 0.887) are close to, but not, the committed production model's.
- **Alert delivery is mock;** no provider is called.
- **Observed history is IMD 1° gridded:** 18 places → 13 distinct series (shared cells disclosed on screen); 2000–2024 in the analysis (the 1991–1999 IMD years feed only the normals).
- Real heatwave days are rare in the record (265 + 5 severe across 18 places in 25 years), mostly in Vidarbha; the Mumbai areas show almost none.

## Not done (out of the frozen scope)
Step 10 (generator v2, retrain, per-zone evaluation); step 11 (integration checkpoints, E2E suite in the repo, CI, deployment, backups); the generated OpenAPI from Node; real notification providers; auto-drafted alerts; forecast-stability and period filters in Analytics; the expiry warning; district boundaries on the map.

## How to run the demo
```sh
# MongoDB running (docs/local-dev-runbook.md step 6a)
SERVICE_ROLE=ml ML_SERVICE_TOKEN=<token> uv run uvicorn heatwave_api.main:app --port 8000   # ML service
cd server && ML_SERVICE_TOKEN=<token> npm run dev                                            # Node API :4000
npm run import-history && npm run score-all                                                  # once: history + predictions
cd ../frontend && npm run dev                                                                 # http://localhost:5173, official / demo-official-local
```
