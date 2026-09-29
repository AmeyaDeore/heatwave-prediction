"""Part 05 settings, from environment variables (see ml/.env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from heatwave_ml.ingestion.settings import ML_DIR, _path


@dataclass(frozen=True)
class EvaluationSettings:
    dataset_path: Path
    risk_config: Path
    selection_policy: Path
    artifact_dir: Path
    registry_dir: Path

    @property
    def runs_dir(self) -> Path:
        return self.artifact_dir / "runs"

    @property
    def experiment_log(self) -> Path:
        return self.artifact_dir / "experiment_log.jsonl"

    @classmethod
    def from_env(cls, env_file: Path | None = ML_DIR / ".env") -> "EvaluationSettings":
        if env_file is not None:
            load_dotenv(env_file, override=False)
        env = os.environ.get
        return cls(
            dataset_path=_path(env("MODELING_DATASET_PATH", "data/heatwave_dataset.csv")),
            risk_config=_path(env("RISK_CONFIG_PATH", "config/risk_classes.yaml")),
            selection_policy=_path(env("MODEL_SELECTION_POLICY", "config/model_selection.yaml")),
            artifact_dir=_path(env("MODEL_ARTIFACT_DIR", "ml/artifacts")),
            registry_dir=_path(env("MODEL_REGISTRY_DIR", "ml/registry")),
        )
