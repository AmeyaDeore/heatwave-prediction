"""The model and its explainer, loaded once at startup (Part 07 §5).

    model = ModelService.load(settings)     # fails here, at startup, if anything is off
    rows = model.predict(raw)               # raw weather -> features -> prediction + SHAP

``predict`` takes raw daily weather in canonical units and runs it through the same
``build_features`` used to build the training set (Part 03), then the explainer's
single predict-and-explain call (Part 06). The backend never computes a feature or
touches SHAP itself.

Picking up a new model is a restart: promote it (heatwave-registry promote), rebuild
its explainer (heatwave-explain build), then restart the service. There is no hot
swap; at this scale a restart is simpler and impossible to get half-right.
"""

import logging
import threading
from datetime import date
from typing import Protocol

import pandas as pd

from heatwave_api.config import Settings
from heatwave_ml.bundle import ModelBundle
from heatwave_ml.explainability.explainer import (
    HeatwaveExplainer,
    explainer_dir,
    load_production_explainer,
)
from heatwave_ml.features import SeasonalNormals, build_features, model_input
from heatwave_ml.registry import ModelRegistry, repo_relative

log = logging.getLogger(__name__)

RAW_COLUMNS = (
    "region_id",
    "date",
    "tmax_c",
    "rh_pct",
    "wind_ms",
    "wind_height_m",
    "solar_mj_m2",
    "precip_mm",
)


class StartupError(RuntimeError):
    """The service cannot serve predictions; it must not start."""


class Predictor(Protocol):
    """What the API needs from the model. Tests substitute a fake."""

    model_version: str
    explainer_id: str
    model_family: str
    normals: SeasonalNormals

    def predict(self, raw: pd.DataFrame) -> list[dict]: ...

    def metadata(self) -> dict: ...


def _metadata_from_report(registry: ModelRegistry, report: dict, version: str) -> dict:
    """Part 05's static test metrics for one model, as Part 08's model_metadata row."""
    c = report["candidates"][version]
    m = c["metrics"]
    return {
        "model_version": version,
        "model_family": c["model_family"],
        "model_sha256": c["model_sha256"],
        "evaluation_id": report["evaluation_id"],
        "policy_version": report["policy"]["version"],
        "report": repo_relative(registry.evaluations_dir / report["evaluation_id"] / "report.md"),
        "test_rows": report["dataset"]["test_rows"],
        "accuracy": m["accuracy"],
        "precision_macro": m["precision_macro"],
        "recall_macro": m["recall_macro"],
        "f1_macro": m["f1_macro"],
        "mean_confidence": c["calibration"]["top_label"]["mean_confidence"],
        "top_label_ece": c["calibration"]["top_label"]["ece"],
        "per_class": m["per_class"],
    }


class ModelService:
    def __init__(self, explainer: HeatwaveExplainer, normals: SeasonalNormals, metadata: dict):
        self.explainer = explainer
        self.normals = normals
        self._metadata = metadata | {"explainer_id": explainer.explainer_id}
        # SHAP's tree explainer and XGBoost are not documented as thread-safe. One
        # explanation takes ~30 ms, so serialising them costs nothing at this scale.
        self._lock = threading.Lock()

    @property
    def model_version(self) -> str:
        return self.explainer.model_version

    @property
    def explainer_id(self) -> str:
        return self.explainer.explainer_id

    @property
    def model_family(self) -> str:
        return self._metadata["model_family"]

    def metadata(self) -> dict:
        return dict(self._metadata)

    @classmethod
    def load(cls, settings: Settings, region_ids: list[str]) -> "ModelService":
        """Load, check and warm up. Any problem raises StartupError with the fix."""
        registry = ModelRegistry(settings.model_registry_dir, settings.runs_dir)
        try:
            if settings.model_version == "production":
                explainer = load_production_explainer(registry)
                pointer = registry.production()
                report = registry.evaluation(pointer["evaluation"]["evaluation_id"])
                version = pointer["model_version"]
            else:
                version = settings.model_version
                entry = next((m for m in registry.models() if m["model_version"] == version), None)
                if entry is None:
                    raise StartupError(f"MODEL_VERSION={version} is not a registered model")
                bundle = ModelBundle.load(registry.resolve(entry))
                explainer = HeatwaveExplainer.load(explainer_dir(registry, version), bundle)
                report = registry.evaluation(entry["last_evaluation"])
            metadata = _metadata_from_report(registry, report, version)
            normals = SeasonalNormals.load(settings.seasonal_normals_file)
        except StartupError:
            raise
        except Exception as exc:  # the message names the command that fixes it
            raise StartupError(f"Cannot load the model or its explainer: {exc}") from exc

        missing = sorted(set(region_ids) - normals.regions)
        if missing:
            raise StartupError(
                f"No seasonal normals for monitored region(s) {missing}; "
                "rebuild them with `uv run heatwave-prepare normals`"
            )
        service = cls(explainer, normals, metadata)
        service._warm_up(region_ids[0])
        log.info(
            "model loaded",
            extra={"model_version": service.model_version, "explainer_id": service.explainer_id},
        )
        return service

    def _warm_up(self, region_id: str) -> None:
        """One real prediction, so the first request is not the one that finds a problem."""
        raw = pd.DataFrame(
            [
                {
                    "region_id": region_id,
                    "date": date.today().isoformat(),
                    "tmax_c": 35.0,
                    "rh_pct": 60.0,
                    "wind_ms": 3.0,
                    "wind_height_m": 10,
                    "solar_mj_m2": 20.0,
                    "precip_mm": 0.0,
                }
            ]
        )
        try:
            self.predict(raw)
        except Exception as exc:
            raise StartupError(f"The model loaded but cannot predict: {exc}") from exc

    def predict(self, raw: pd.DataFrame) -> list[dict]:
        """One result per row of ``raw`` (RAW_COLUMNS), in order:
        ``features`` (the computed feature values before imputation, NaN = missing)
        and ``prediction`` (Part 06's Explanation.to_dict())."""
        features = build_features(raw[list(RAW_COLUMNS)].reset_index(drop=True), self.normals)
        with self._lock:
            explanations = self.explainer.explain(model_input(features))
        return [
            {"features": features.iloc[i].to_dict(), "prediction": e.to_dict()}
            for i, e in enumerate(explanations)
        ]
