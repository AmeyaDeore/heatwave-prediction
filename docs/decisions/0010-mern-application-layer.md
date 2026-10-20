# ADR 0010: MERN application layer with a FastAPI ML service (Revision 2)

- **Status:** Accepted (plan). Implementation follows the Revision 2 sections of Parts 01–18
- **Date:** 2026-10-20
- **Part:** cross-cutting (master plan §5, Parts 07, 08, 09, 15)
- **Supersedes in part:** [ADR 0006](0006-backend-api.md) (where the public API runs), [ADR 0007](0007-database.md) (SQLite as the application store), [ADR 0008](0008-notification-service.md) (the notification service's runtime)

## Context

The examiner made five features mandatory: user login (M1), MongoDB integration (M2), data analysis for places in Maharashtra (M3), a Maharashtra map (M4), and an alert system using Node.js and MongoDB (M5). The team's application stack is MERN.

At this point the project had:
- a complete Python ML pipeline (Parts 02–06),
- a FastAPI service on SQLite with login, alerts and notifications (Parts 07–09), and
- a React frontend foundation (Part 10).

The live prediction path must use the same Python feature module, model and explainer as training (Part 03 §6). That is the system's highest-risk seam (Part 16 §4).

The examiner gave no exhaustive list of cities or filters.

## Decision

1. **Node.js + Express (TypeScript) on MongoDB is the application API** (`server/`). The React app calls only this API. It owns login and users, persistence of predictions and weather snapshots, alerts and notifications, analytics, and map data.
2. **The existing FastAPI service stays as the internal ML inference service** (`backend/`, `SERVICE_ROLE=ml`). It owns live features, prediction, SHAP and recommended actions. It gains two additive internal endpoints (`POST /predict/batch`, `GET /model`) and is reachable only from the Node API, with a service token.
3. **The `/api/v1` contract in `docs/api/README.md` is kept** (envelope, error taxonomy, field names, the three risk classes) and extended additively. `openapi.json` becomes generated from the Node schemas.
4. **MongoDB replaces SQLite as the application store.** The entity model carries over. Factors and channel deliveries are embedded arrays, so issuing an alert is one atomic write. Integrity rules that SQLite enforced with constraints and triggers are enforced with validators, unique and TTL indexes, and conditional writes.
5. **The notification service is ported to Node with identical semantics**, read from the same `config/` files. The Python implementation and its tests are the specification.
6. **Predictions can suggest alerts but never send them:** a HEATWAVE+ prediction creates a DRAFT with `origin: auto_draft`, and only an official issues it.
7. **Login is required for the whole app**, except health and the public advisory feed.
8. **Maharashtra places are our proposed, configurable selection:** 14 cities across all six divisions, plus the existing Mumbai areas. Each place lands together with its seasonal normals. The model is retrained on a v2 synthetic dataset with per-place climatology and the plains zone, using the existing pipeline unchanged.

## Alternatives considered

- **Keep FastAPI as the main API, with a Node.js service for alerts only.** There would be less porting, but login would be split across two backends and the frontend would talk to both. It also meets "MERN" only nominally.
- **Rewrite inference in Node.** Rejected. It would duplicate feature computation and SHAP, breaking the parity guarantee the whole plan protects.
- **Keep SQLite beside MongoDB.** Rejected. Two application databases would be the source-of-truth ambiguity Part 08 §8 warns against.
- **Mongoose models with `$jsonSchema` validators vs. the native driver only.** Mongoose is the common MERN choice and gives typed schemas. Validators are kept in the database too, so the rules hold for any writer.
- **A map library (Leaflet) with third-party tiles.** Rejected (revised 2026-10-20, to avoid unnecessary technologies). A committed, simplified Maharashtra boundary GeoJSON rendered as plain SVG covers a state-scale map with no new dependency, no keys and no network calls, and takes every colour from the design tokens. A tile library can sit behind the same component later if street-level detail is ever needed.
- **Computing heatwave labels for observed history in Node.** Rejected. The `IMD-HW-DAILY-v1` rule runs only in Python (`criteria.classify`), which exports labelled history for Node to import, so there is one implementation of the rule, as there is one of the features.

## Consequences

- Parts 02–06 and the frontend foundation are reused as built. The FastAPI service is reused as the ML service. Its SQLite, alert, notification and auth code stays in the repository as the reference, retired from the request path after Part 16 R2.
- The frontend changes only in its base URL, the token on reads, the login page and guard, the map component and the additive types.
- Deployment grows from one service + a file to three services + MongoDB (Part 18 R2).
- New risks to manage: version agreement across services (Part 16 checkpoint 3.7), and two service-to-service failure modes (ML service down, MongoDB down).
- Platform reproducibility of the model: the production bundle is built on one designated platform and shipped as an artifact (Part 04 R2).
