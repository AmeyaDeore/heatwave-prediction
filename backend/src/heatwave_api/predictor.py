"""The model + explainer behind POST /predict (Part 05 model, Part 06 explainer).

Loaded once at startup. Refuses to start on a missing, tampered or stale artifact
(`load_production_explainer` checks all three), so the service can't come up "healthy"
and then fail on its first real prediction (Part 07 §5).
"""

import threading
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from heatwave_api.config import Settings
from heatwave_api.errors import ModelUnavailable, PredictionFailed
from heatwave_api.weather import WeatherReading
from heatwave_ml.explainability.explainer import ExplainerError, load_production_explainer
from heatwave_ml.features import FEATURE_COLUMNS, SeasonalNormals, build_features, model_input
from heatwave_ml.registry import ModelRegistry


@dataclass(frozen=True)
class PredictorInfo:
    model_version: str
    explainer_id: str
    model_family: str
    labeling_rule_version: str
    evaluation: dict  # the promotion pointer's test metrics, static per model version


@dataclass(frozen=True)
class PredictionResult:
    """``prediction`` is Explanation.to_dict() unchanged (Part 06 contract);
    ``inputs`` are the feature values before imputation (None = missing)."""

    prediction: dict
    inputs: dict[str, float | None]


class Predictor(Protocol):
    info: PredictorInfo

    def predict(self, reading: WeatherReading) -> PredictionResult: ...

    def inputs(self, reading: WeatherReading) -> dict[str, float | None]:
        """Just the feature values (normal and deviation included), without scoring."""
        ...


class ProductionPredictor:
    def __init__(self, explainer, normals: SeasonalNormals, info: PredictorInfo):
        self.explainer = explainer
        self.normals = normals
        self.info = info
        # SHAP's C extension is not documented as thread-safe; requests run in a thread pool.
        self._lock = threading.Lock()

    @classmethod
    def load(cls, settings: Settings) -> "ProductionPredictor":
        if settings.model_version != "production":
            raise ModelUnavailable(
                "MODEL_VERSION pinning is not supported: set it to 'production' and "
                "promote the version you want with `heatwave-registry promote`."
            )
        registry = ModelRegistry(settings.model_registry_dir, settings.model_artifact_dir / "runs")
        try:
            explainer = load_production_explainer(registry)
            pointer = registry.production()
            normals = SeasonalNormals.load(settings.seasonal_normals_file)
        except Exception as exc:  # any artifact problem must stop startup, with its reason
            raise ModelUnavailable(
                f"Cannot load the production model and explainer: {exc}"
            ) from exc
        info = PredictorInfo(
            model_version=explainer.model_version,
            explainer_id=explainer.explainer_id,
            model_family=pointer["model_family"],
            labeling_rule_version=pointer["training_data"]["labeling_rule_version"],
            evaluation=pointer["evaluation"],
        )
        return cls(explainer, normals, info)

    def _features(self, reading: WeatherReading) -> pd.DataFrame:
        raw = pd.DataFrame(
            [
                {
                    "region_id": reading.region_id,
                    "date": pd.Timestamp(reading.date),
                    "tmax_c": reading.tmax_c,
                    "rh_pct": reading.rh_pct,
                    "wind_ms": reading.wind_ms,
                    "wind_height_m": reading.wind_height_m,
                    "solar_mj_m2": reading.solar_mj_m2,
                    "precip_mm": reading.precip_mm,
                }
            ]
        )
        try:
            return build_features(raw, self.normals)
        except (ValueError, KeyError) as exc:
            raise PredictionFailed("These conditions could not be turned into features.") from exc

    @staticmethod
    def _inputs(features: pd.DataFrame) -> dict[str, float | None]:
        row = features.iloc[0]
        return {c: None if pd.isna(row[c]) else round(float(row[c]), 4) for c in FEATURE_COLUMNS}

    def inputs(self, reading: WeatherReading) -> dict[str, float | None]:
        return self._inputs(self._features(reading))

    def predict(self, reading: WeatherReading) -> PredictionResult:
        features = self._features(reading)
        try:
            with self._lock:
                explanation = self.explainer.explain(model_input(features))[0]
        except (ValueError, KeyError, ExplainerError) as exc:
            raise PredictionFailed("The model could not score these conditions.") from exc
        return PredictionResult(prediction=explanation.to_dict(), inputs=self._inputs(features))
