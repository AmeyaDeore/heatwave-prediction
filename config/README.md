# config/

Non-secret configuration that more than one part of the system reads. Each value is defined here once, and ml/ and backend/ point to it through env vars. Do not duplicate it in code.

| File | Read by | Env var pointing at it |
|------|---------|------------------------|
| `risk_classes.yaml` | ml (labelling), backend (validation) | `RISK_CONFIG_PATH` |
| `regions.yaml` | ml (ingestion), backend (upserted into the `regions` table at startup, Part 08) | `MONITORED_REGIONS_FILE` |
| `seasonal_normals.csv` | ml (features, labels, synthetic generator), backend (live features, Part 07) | `SEASONAL_NORMALS_FILE` |
| `model_selection.yaml` | ml (evaluation, Part 05; explainer latency budget, Part 06) | `MODEL_SELECTION_POLICY` |
| `alert_channels.yaml` | backend (alert channel ids and labels, Part 07; delivery `mechanism` sms/email/in_app, Part 09) | `ALERT_CHANNELS_FILE` |
| `notification_templates.yaml` | backend (message wording per mechanism, SMS length rule, Part 09) | `NOTIFICATION_TEMPLATES_FILE` |
| `notification_recipients.yaml` | backend (distribution lists per channel and region, Part 09). **Development list only**: `.invalid` addresses and Twilio test numbers. Deployments point the env var at their own, uncommitted file | `NOTIFICATION_RECIPIENTS_FILE` |
| `recommended_actions.yaml` | backend (risk class + top factors → authority actions, Part 07) | `RECOMMENDED_ACTIONS_FILE` |
| `feature_labels.json` | ml (`features/schema.py`, explanations), backend (Part 07), frontend (Parts 10–14) | none: fixed path, imported directly |

`model_selection.yaml` is the production-model selection policy. Change it only **before** a test evaluation, in its own commit, and bump `policy_version`: `heatwave-evaluate run` refuses to score the test split while this file has uncommitted changes (see `docs/ml/evaluation.md` §2).

`seasonal_normals.csv` is **generated**, not hand-edited: `uv run heatwave-prepare normals` derives it from landed IMD history (1991–2020, ±15-day smoothing; see `docs/data/heatwave-labeling-spec.md` §5). Rebuild it after adding a region to `regions.yaml`. A rebuild changes labels, so the dataset build then asks for `--force`.

Secrets never go in this directory. They belong in the per-concern `.env` files.

`feature_labels.json` is the one table of user-facing names: feature labels, display units and precision, and risk-class display names (Part 06 §5). Its feature keys must equal `FEATURE_COLUMNS` in order, and `heatwave_ml.features.schema` refuses to import otherwise. Rename a label here, never in code. The API also returns each factor's `label`/`unit`/`display_value`, so the frontend and backend cannot disagree.
