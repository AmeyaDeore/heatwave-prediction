"""The model artifact bundle (Part 04 §5), shared by training, evaluation and serving.

A bundle is one directory:

    model.joblib   the fitted sklearn Pipeline: ("pre", imputer → scaler | passthrough),
                   then ("clf", estimator). Preprocessing is inside the model object, so
                   inference-time transformation is identical to training-time by construction.
    bundle.json    the contract: version id, dataset hash, ordered input/feature columns,
                   class index → label mapping, preprocessing marker, hyperparameters,
                   library versions, and a prediction fingerprint.

Part 05 evaluates bundles, Part 06 explains them, Part 07 serves them. None of them
retrains or re-derives anything in bundle.json. Load with ``ModelBundle.load``,
which refuses a bundle whose file hash, library versions, feature list or class
mapping don't match what was recorded at training time.

model.joblib is a pickle: only load bundles this pipeline produced. The SHA-256
check runs before unpickling, so a swapped or corrupted file is rejected, not run.
"""

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.pipeline import Pipeline

BUNDLE_SCHEMA_VERSION = 1
MODEL_FILE = "model.joblib"
METADATA_FILE = "bundle.json"

# Pickled estimators are only safe to load with the library versions that wrote them.
PINNED_LIBRARIES = ("scikit-learn", "xgboost")


class BundleError(RuntimeError):
    """The bundle is missing, tampered with, or inconsistent with its own contract."""


def library_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        "xgboost": xgboost.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "joblib": joblib.__version__,
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prediction_fingerprint(proba: np.ndarray) -> str:
    """SHA-256 of the raw float64 probabilities: equal only if predictions are bit-identical."""
    return hashlib.sha256(np.ascontiguousarray(proba, dtype="<f8").tobytes()).hexdigest()


def scaling_marker(pipeline: Pipeline) -> str:
    """The scale step: "StandardScaler" when fitted, "passthrough" for the tree no-op."""
    step = pipeline.named_steps["pre"].named_steps["scale"]
    return step if isinstance(step, str) else type(step).__name__


def save_bundle(directory: Path, pipeline: Pipeline, metadata: dict) -> dict:
    """Write model.joblib, then bundle.json with its hash. Refuses to overwrite a bundle."""
    if (directory / METADATA_FILE).exists():
        raise BundleError(f"{directory} already holds a bundle; bundles are immutable")
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / MODEL_FILE
    joblib.dump(pipeline, model_path)
    metadata = {
        "bundle_schema": BUNDLE_SCHEMA_VERSION,
        **metadata,
        "model_file": MODEL_FILE,
        "model_sha256": sha256_file(model_path),
        "library_versions": library_versions(),
    }
    (directory / METADATA_FILE).write_text(
        json.dumps(metadata, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return metadata


@dataclass(frozen=True)
class ModelBundle:
    directory: Path
    metadata: dict
    pipeline: Pipeline

    @property
    def version(self) -> str:
        return self.metadata["model_version"]

    @property
    def family(self) -> str:
        return self.metadata["model_family"]

    @property
    def input_columns(self) -> list[str]:
        """What ``predict_proba`` needs: the features plus ``month`` (imputer input)."""
        return list(self.metadata["input_columns"])

    @property
    def feature_columns(self) -> list[str]:
        """The model's features, in the exact order the estimator was fit on."""
        return list(self.metadata["feature_columns"])

    @property
    def class_labels(self) -> dict[int, str]:
        """Class index → label, e.g. {0: "NORMAL", 1: "HEATWAVE", 2: "SEVERE_HEATWAVE"}."""
        return {int(i): label for i, label in self.metadata["class_labels"].items()}

    @classmethod
    def load(cls, directory: Path, *, check_versions: bool = True) -> "ModelBundle":
        directory = Path(directory)
        meta_path = directory / METADATA_FILE
        if not meta_path.exists():
            raise BundleError(f"No {METADATA_FILE} in {directory}")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("bundle_schema") != BUNDLE_SCHEMA_VERSION:
            raise BundleError(
                f"{directory}: bundle schema {metadata.get('bundle_schema')}, "
                f"this code reads {BUNDLE_SCHEMA_VERSION}"
            )

        model_path = directory / metadata["model_file"]
        if sha256_file(model_path) != metadata["model_sha256"]:
            raise BundleError(f"{model_path} does not match the SHA-256 in {METADATA_FILE}")

        if check_versions:
            current = library_versions()
            drift = {
                lib: (metadata["library_versions"].get(lib), current[lib])
                for lib in PINNED_LIBRARIES
                if metadata["library_versions"].get(lib) != current[lib]
            }
            if drift:
                raise BundleError(
                    f"{directory} was trained with different library versions "
                    f"(trained, installed): {drift}. Run `uv sync` or retrain."
                )

        pipeline = joblib.load(model_path)
        bundle = cls(directory, metadata, pipeline)
        bundle._check_consistency()
        return bundle

    def _check_consistency(self) -> None:
        """The pickled model must agree with its own contract."""
        if not isinstance(self.pipeline, Pipeline) or list(self.pipeline.named_steps) != [
            "pre",
            "clf",
        ]:
            raise BundleError(f"{self.directory}: model is not a pre → clf Pipeline")
        if list(self.pipeline.feature_names_in_) != self.input_columns:
            raise BundleError(f"{self.directory}: pipeline input columns differ from bundle.json")
        clf = self.pipeline.named_steps["clf"]
        fitted_features = getattr(clf, "feature_names_in_", None)
        if fitted_features is not None and list(fitted_features) != self.feature_columns:
            raise BundleError(f"{self.directory}: estimator feature order differs from bundle.json")
        if [int(c) for c in clf.classes_] != sorted(self.class_labels):
            raise BundleError(f"{self.directory}: estimator classes differ from class_labels")
        if scaling_marker(self.pipeline) != self.metadata["preprocessing"]["scale"]:
            raise BundleError(f"{self.directory}: preprocessing step differs from bundle.json")

    def _select(self, frame: pd.DataFrame) -> pd.DataFrame:
        # Columns are taken by name, so a caller's column order can never silently
        # permute the features.
        missing = [c for c in self.input_columns if c not in frame.columns]
        if missing:
            raise KeyError(f"Model {self.version} needs columns {missing}")
        return frame[self.input_columns]

    def predict_proba(self, frame: pd.DataFrame) -> pd.DataFrame:
        """One column per class label, in class-index order; rows keep ``frame.index``."""
        proba = self.pipeline.predict_proba(self._select(frame))
        labels = [self.class_labels[i] for i in sorted(self.class_labels)]
        return pd.DataFrame(proba, columns=labels, index=frame.index)

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        """The most probable class label per row."""
        return self.predict_proba(frame).idxmax(axis=1).rename("risk_class")
