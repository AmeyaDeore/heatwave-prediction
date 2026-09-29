"""Part 03 settings, from environment variables (see ml/.env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from heatwave_ml.ingestion.settings import ML_DIR, _path


@dataclass(frozen=True)
class PreparationSettings:
    risk_config: Path
    seasonal_normals_file: Path
    dataset_path: Path
    processed_dir: Path
    sample_dir: Path
    random_seed: int
    test_fraction: float
    validation_fraction: float

    @property
    def manifest_path(self) -> Path:
        return self.dataset_path.with_suffix(".manifest.json")

    @classmethod
    def from_env(cls, env_file: Path | None = ML_DIR / ".env") -> "PreparationSettings":
        if env_file is not None:
            load_dotenv(env_file, override=False)
        env = os.environ.get
        settings = cls(
            risk_config=_path(env("RISK_CONFIG_PATH", "config/risk_classes.yaml")),
            seasonal_normals_file=_path(
                env("SEASONAL_NORMALS_FILE", "config/seasonal_normals.csv")
            ),
            dataset_path=_path(env("MODELING_DATASET_PATH", "data/heatwave_dataset.csv")),
            processed_dir=_path(env("PROCESSED_DATA_DIR", "data/processed")),
            sample_dir=_path(env("SAMPLE_DATA_DIR", "data/sample")),
            random_seed=int(env("RANDOM_SEED", "42")),
            test_fraction=float(env("TEST_FRACTION", "0.15")),
            validation_fraction=float(env("VALIDATION_FRACTION", "0.15")),
        )
        if not 0 < settings.test_fraction + settings.validation_fraction < 1:
            raise ValueError("TEST_FRACTION + VALIDATION_FRACTION must be between 0 and 1")
        return settings
