"""Part 04 settings, from environment variables (see ml/.env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from heatwave_ml.ingestion.settings import ML_DIR, _path


@dataclass(frozen=True)
class TrainingSettings:
    dataset_path: Path
    risk_config: Path
    artifact_dir: Path
    random_seed: int
    cv_folds: int
    n_jobs: int  # parallel CV fits; every individual fit is single-threaded

    @property
    def manifest_path(self) -> Path:
        return self.dataset_path.with_suffix(".manifest.json")

    @property
    def experiment_log(self) -> Path:
        return self.artifact_dir / "experiment_log.jsonl"

    @property
    def runs_dir(self) -> Path:
        return self.artifact_dir / "runs"

    @classmethod
    def from_env(cls, env_file: Path | None = ML_DIR / ".env") -> "TrainingSettings":
        if env_file is not None:
            load_dotenv(env_file, override=False)
        env = os.environ.get
        settings = cls(
            dataset_path=_path(env("MODELING_DATASET_PATH", "data/heatwave_dataset.csv")),
            risk_config=_path(env("RISK_CONFIG_PATH", "config/risk_classes.yaml")),
            artifact_dir=_path(env("MODEL_ARTIFACT_DIR", "ml/artifacts")),
            random_seed=int(env("RANDOM_SEED", "42")),
            cv_folds=int(env("CV_FOLDS", "5")),
            n_jobs=int(env("TRAINING_N_JOBS", "-1")),
        )
        if settings.cv_folds < 2:
            raise ValueError("CV_FOLDS must be at least 2")
        return settings
