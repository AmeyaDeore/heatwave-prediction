# Log: implementation plan Revision 2 (examiner feedback)

| | |
|---|---|
| Plan | `Implementation/00-README-master-plan.md` and the "Revision 2" section of each part 01–18 |
| Status | Plan revised. No code changed. Implementation follows the master plan §4.1 sequence |
| Date | 2026-10-20 |
| Branch / commits | `part-10/frontend-architecture` (uncommitted at the time of writing) |
| Tests | Not applicable (documentation only). Nothing executable changed |

## Summary

The examiner made five features mandatory: user login (M1), MongoDB integration (M2), data analysis for Maharashtra places (M3), a Maharashtra map (M4), and an alert system on Node.js + MongoDB (M5). They were folded into the existing 18-part plan as a **Revision 2 (R2)** section in each affected part. There is no separate roadmap. The application layer becomes MERN. The completed ML pipeline and the FastAPI service are kept, the latter as the internal ML inference service. The `/api/v1` contract is preserved, so the completed frontend foundation carries over.

## What changed, by document

| Document | Change |
|---|---|
| `Implementation/00-README-master-plan.md` | Revision note with the M1–M5 → part map; §1 summary note; §2.1 R2 architecture diagram and three rules; R2 ownership table; §4.1 R2 build sequence with dependencies; §5 updated locked decisions; §7 R2 definition of done |
| `CLAUDE.md` | Locked decisions mirrored from master plan §5: MERN app stack, FastAPI ML service, MongoDB, Maharashtra places, login required, alerts suggested but only issued by people |
| Part 01 | `server/` workspace, Node/TypeScript tooling, local MongoDB, new env vars, runbook steps |
| Part 02 | **Proposed** place set (14 cities across the 6 divisions + the existing Mumbai areas), `division`/`kind`/`parent` fields, data pulls with the existing adapters, the place-with-normals ordering rule |
| Part 03 | Normals for every place; synthetic generator `imd-sim-v2` (per-place climatology, raised Tmax cap, slot weighting); split stratified by class and zone |
| Parts 04–06 | Re-run on v2 with per-zone metrics and a per-zone dangerous-failure gate; platform-reproducibility finding; explainer rebuild with inland sanity cases |
| Part 07 | §A FastAPI as the ML service (`SERVICE_ROLE=ml`, `/predict/batch`, `/model`, service token). §B the Node API: contract rules, R2 endpoint inventory (adds `/auth/logout`, `/predictions/batch`, `/predictions/latest-by-region`), the `ML_SERVICE_UNAVAILABLE` code, generated OpenAPI, transition plan |
| Part 08 | MongoDB collections mapped from every SQLite table, indexes, the replacement for each SQLite integrity rule, migrations, seeding, backups |
| Part 09 | Node port with identical semantics; the prediction → draft-suggestion rule (never dispatches) |
| Part 10 | Login page, route guard and logout; `MaharashtraMap` (plain SVG from a committed boundary GeoJSON, risk and sequential scales, accessible table equivalent; revised from Leaflet, see the update below); place grouping by division; Node base URL |
| Part 11 | Maharashtra map + table panel, lead-day switch, division filter, one composite call; the owner's decisions recorded (row/marker click selects and stays; "score missing" button **and** seeding CLI; scratch-registry verification) |
| Part 12 | Place selection, lead-day tabs, zone note, link to a suggested draft after recompute |
| Part 13 | "Suggested by the model" drafts, filters, targeting across Maharashtra; Response Coordination still open |
| Part 14 | Weather-history import, observed-history labels, **our proposed** filters (place, division, period, data, lead day), place-comparison panel and map view, per-zone model performance |
| Part 15 | Login in Node + MongoDB: one role, JWT 60 min, logout via revoked token ids, lockout, CLI-managed accounts, rewritten auth matrix (login required everywhere except health and the advisory feed) |
| Parts 16–18 | Checkpoints 3.7–3.12 (one per mandatory feature plus the Node ↔ ML seam); new test layers and E2E journey; deployment of three services + MongoDB |
| `docs/decisions/0010-mern-application-layer.md` | New ADR. 0006/0007/0008 marked "superseded in part" |

## Key decisions and why

- **Node application API + FastAPI ML service (owner's choice, 2026-10-20).** It meets MERN for every application concern while keeping the single Python path for features, predictions and SHAP, the seam Part 16 §4 calls the highest-risk in the system.
- **Contract kept, extended additively.** The frontend's client, hooks and contract tests carry over. Only the base URL, the token on reads and new optional fields change.
- **Revision sections, not rewrites.** Original plan text and ticked checklists stay as the record of what was built. Each R2 section has its own acceptance criteria.
- **Places are our proposal (owner's instruction).** The examiner gave no list of cities or filters. Places and filters are labelled as our proposal and kept configurable, and no filter is presented as examiner-mandated.
- **Retrain before trusting inland risk.** The training data only covers coastal Mumbai (generator v1 uses Mumbai climatology and caps Tmax at 44 °C), so the plan re-runs Parts 03–06 on v2 data rather than extrapolating.

## Verification

Documentation only. `git status` was checked before and after: only Markdown files under `Implementation/`, `docs/` and `CLAUDE.md` changed, plus two new docs files. No source, config or data file was touched by this revision.

## Open items

- `config/regions.yaml`, `docs/api/README.md`, `docs/database/README.md`, `docs/notifications/README.md`, `config/README.md` and the top-level `README.md` describe the **implemented** system and change only when each R2 part is implemented.
- Confirm the proposed place set with the team and examiner (Part 02 R2 acceptance).
- Choose the Maharashtra boundary GeoJSON source and confirm its licence (Part 10 R2.2).
- Part 13 still owes the Response Coordination decision. Part 14 still owes the event-counting rule.

## Handoff

> Start with master plan §4.1: R2-0 (Part 01 R2: `server/` + MongoDB), then the ML track (02 → 03 → 04–06 re-run) and the app track (07 §A → 08 R2 → 07 §B → 15 R2 → 09 R2) in parallel, then the frontend (10 R2 → 11 → 12 → 13 → 14), then 16–18. Each part's "Revision 2" section lists its own acceptance criteria. The app track can be built against the five existing Mumbai areas until the ML track lands the new places and the retrained model.

## Update 2026-10-20: owner's clarifications reviewed against the code

The owner clarified five requirements: the map and places use our actual data and stay configurable as our selection; the analysis is a real feature; the existing project is preserved; MERN with FastAPI kept only for ML; and implementation goes step by step. The plan was checked against the code, which found conflicts the first revision missed.

**Code facts found (read-only inspection):**
- Both Python region loaders (`heatwave_ml.ingestion.regions.Region(**entry)`, `heatwave_api.catalog.RegionInfo(**r)`) reject unknown YAML keys. Adding `division`/`kind`/`parent` would crash ingestion and the API, so a small loader change must land first.
- No artifact pins the normals file hash. The dataset build checks normals per row, by value. Extending the normals for new places is therefore safe if the existing five rows stay byte-identical.
- Real history for analysis is IMD gridded Tmax 1991–2024 (the normals' own source). At 1° the Mumbai areas share two cells. `data/raw/` is empty on the current development machine, so it must be re-pulled.
- The forecast file is the committed 2026-09-28 sample, and `docs/api/openapi.json` is currently generated from FastAPI.

**Plan changes:**
- Master plan §4.1 rewritten as 11 small, validated steps, with what each validates and its dependencies.
- New §4.2 conflict register (C1–C12).
- §7 M3/M4 definitions of done sharpened.
- Part 01 R2: a dependency budget (and what is deliberately not added).
- Part 02 R2: the loader fix; what "actual data" means per source; shared IMD cells; the 6-hourly refresh through the existing scheduled-pull path.
- Part 03 R2: normals extended without touching existing rows; a Python-labelled observed-history export.
- Part 07: the OpenAPI file split, a freeze of the FastAPI `app` role during the transition, the `import-history` CLI.
- Part 08: the `history_summaries` collection, unique keys on snapshots; the geo index dropped as unneeded.
- Part 10: the map is plain SVG (no Leaflet, no tiles, no new dependency), with risk and sequential scales and a Mumbai inset.
- Part 11: map layers for predicted risk, forecast Tmax and departure; freshness; the inland model caveat; "Analyse"/"Compare" into Part 14.
- Part 14 R2 rewritten: panels A1–A10 over observed history, patterns and predictions; definitions of heatwave day, event, spell and trend; our proposed filters; precomputed summaries.
- ADR 0010: the alternatives updated.

## Update 2026-10-20 (later): documentation status audit

The owner asked whether the `Implementation/` files were kept current through implementation. Checked against the files and the code, not from memory:
- **Coverage:** all 19 plan files carry Revision 2 content. Each of M1–M5 maps to its implementing parts (M1: 01, 07, 10, 15, 16; M2: 01, 07, 08, 15, 16; M3: 02, 14, 16; M4: 02, 10, 11, 12, 16; M5: 07, 09, 13, 16). The owner's clarifications (actual data, real analysis, places and filters labelled as our proposal, minimal MERN, incremental steps) are in Parts 00, 01, 02, 03, 10, 11 and 14.
- **Status gaps found and fixed:**
  - No file said which R2 work was done. Added a status board (master plan §4.0) and an "R2 status" line in every part.
  - Part 15's checklist showed 0 of 8 done, although Parts 07/08/10 built login, hashing, tokens, the rate limit and frontend expiry handling. It now has 4 ticked, with evidence; logout, the login screen and Issue-Warning UI gating are annotated as not built.
  - Part 17 had none ticked, although the explanation sanity checks are automated. It is now 1 ticked, with the partial items annotated.
  - Part 01 R2's pre-commit item was done but unticked. Now ticked.
  - Part 10's ticks were accurate, but did not say the work is uncommitted. Note added.
- **Nothing was marked complete that is not built.** Every R2 section except Part 01's is "Not started".
