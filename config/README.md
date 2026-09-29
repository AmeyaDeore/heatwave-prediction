# config/

Non-secret configuration that more than one part of the system reads. Each value is defined here once, and ml/ and backend/ point to it through env vars. Do not duplicate it in code.

| File | Read by | Env var pointing at it |
|------|---------|------------------------|
| `risk_classes.yaml` | ml (labelling), backend (validation) | `RISK_CONFIG_PATH` |
| `regions.yaml` | ml (ingestion), backend/db seed (Part 08) | `MONITORED_REGIONS_FILE` |
| `seasonal_normals.csv` | ml (features, labels, synthetic generator), backend (live features, Part 07) | `SEASONAL_NORMALS_FILE` |

`seasonal_normals.csv` is **generated**, not hand-edited: `uv run heatwave-prepare normals` derives it from landed IMD history (1991–2020, ±15-day smoothing; see `docs/data/heatwave-labeling-spec.md` §5). Rebuild it after adding a region to `regions.yaml`. A rebuild changes labels, so the dataset build then asks for `--force`.

Secrets never go in this directory. They belong in the per-concern `.env` files.
