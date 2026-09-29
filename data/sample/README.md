# data/sample/

A small committed dataset. With it, backend (Part 07) and frontend (Parts 10–14) development can start without waiting for the ML pipeline.

| File | From | Contents |
|------|------|----------|
| `forecast_features.csv` | Part 03 (`uv run heatwave-prepare sample`) | The latest Open-Meteo forecast (today + 3 days) for every region in `config/regions.yaml`, passed through the **live-inference feature path** (`heatwave_ml.features.build_features`). It has the exact columns a prediction request is built from, including `lead_days` and `issued_at`. |

Predictions (risk class, probability, SHAP top factors) are added here once a model exists (Parts 04–06).
