# config/

Non-secret configuration that more than one part of the system reads. Each value is defined here once, and ml/ and backend/ point to it through env vars. Do not duplicate it in code.

| File | Read by | Env var pointing at it |
|------|---------|------------------------|
| `risk_classes.yaml` | ml (labelling), backend (validation) | `RISK_CONFIG_PATH` |
| `regions.yaml` | ml (ingestion), backend/db seed (Part 08) | `MONITORED_REGIONS_FILE` |

Secrets never go in this directory. They belong in the per-concern `.env` files.
