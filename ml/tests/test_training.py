"""Part 04: training pipeline, experiment log and the model bundle contract."""

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import train_test_split

from heatwave_ml.bundle import (
    BundleError,
    ModelBundle,
    prediction_fingerprint,
    save_bundle,
)
from heatwave_ml.features import FEATURE_COLUMNS, MONTH_COLUMN, TARGET_COLUMN, model_input
from heatwave_ml.ingestion.settings import REPO_ROOT
from heatwave_ml.preprocessing.dataset import sha256_of
from heatwave_ml.training import cli
from heatwave_ml.training.experiment_log import ExperimentLog
from heatwave_ml.training.models import (
    MODEL_FAMILIES,
    NO_WEIGHTING,
    SAMPLE_WEIGHT,
    default_specs,
    describe_space,
    quick_specs,
)
from heatwave_ml.training.trainer import Trainer, load_training_data

FOLDS = 3


def write_small_dataset(directory, *, rows_per_split=(600, 200, 200)):
    """A stratified slice of the committed dataset, with a matching manifest.

    Test-split rows get a missing Tmax: the fitted imputer raises on those, so if
    any test row reached a fit or a prediction, training would fail.
    """
    source = REPO_ROOT / "data" / "heatwave_dataset.csv"
    full = pd.read_csv(source, dtype={"region_id": str})
    parts = []
    for split, n in zip(("train", "validation", "test"), rows_per_split, strict=True):
        frame = full[full["split"] == split]
        part, _ = train_test_split(
            frame, train_size=n, stratify=frame[TARGET_COLUMN], random_state=0
        )
        parts.append(part)
    small = pd.concat(parts).sort_index()
    small.loc[small["split"] == "test", "tmax_c"] = np.nan

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "heatwave_dataset.csv"
    small.to_csv(path, index=False, lineterminator="\n")
    manifest = json.loads(source.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    manifest["sha256"] = sha256_of(path)
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def make_trainer(data, artifacts, **kwargs):
    return Trainer(
        data,
        quick_specs(),
        runs_dir=artifacts / "runs",
        experiment_log=ExperimentLog(artifacts / "experiment_log.jsonl"),
        seed=42,
        cv_folds=FOLDS,
        n_jobs=1,
        **kwargs,
    )


@pytest.fixture(scope="module")
def trained(tmp_path_factory, criteria):
    """Two complete quick runs on the same data, into the same artifact directory."""
    root = tmp_path_factory.mktemp("training")
    data = load_training_data(write_small_dataset(root / "data"), criteria)
    artifacts = root / "artifacts"
    first = make_trainer(data, artifacts)
    first_results = first.run()
    log_after_first = (artifacts / "experiment_log.jsonl").read_text(encoding="utf-8")
    second = make_trainer(data, artifacts)
    second_results = second.run()
    return {
        "data": data,
        "artifacts": artifacts,
        "runs": (first, second),
        "results": (first_results, second_results),
        "log_after_first": log_after_first,
    }


# --- the pipeline -----------------------------------------------------------------


def test_poisoned_test_split_would_break_training(trained):
    """Proves the poison works, so the successful runs above never touched a test row."""
    frame = pd.read_csv(trained["data"].dataset_path)
    test_rows = frame[frame["split"] == "test"]
    assert test_rows["tmax_c"].isna().all()
    pipeline = quick_specs()["random_forest"].pipeline(42)
    with pytest.raises(ValueError, match="must be present"):
        pipeline.fit(model_input(test_rows), test_rows[TARGET_COLUMN])


def test_training_data_excludes_test_split(trained):
    data = trained["data"]
    assert len(data.train) == 600 and len(data.validation) == 200
    assert not data.train["tmax_c"].isna().any()
    assert not data.validation["tmax_c"].isna().any()


def test_training_is_reproducible(trained):
    """Same data + seed + hyperparameters → bit-identical predictions."""
    first, second = trained["results"]
    for family in MODEL_FAMILIES:
        assert first[family].version != second[family].version
        assert first[family].best_params == second[family].best_params
        assert first[family].tuned_cv == second[family].tuned_cv
        assert first[family].fingerprint == second[family].fingerprint

    X_val, _ = trained["data"].xy("validation")
    for family in MODEL_FAMILIES:
        a = ModelBundle.load(first[family].bundle_dir).predict_proba(X_val).to_numpy()
        b = ModelBundle.load(second[family].bundle_dir).predict_proba(X_val).to_numpy()
        assert np.array_equal(a, b)


def test_final_models_use_the_documented_imbalance_strategy(trained):
    first, _ = trained["results"]
    for family in ("logistic_regression", "random_forest"):
        clf = ModelBundle.load(first[family].bundle_dir).pipeline.named_steps["clf"]
        assert clf.class_weight == "balanced"

    xgb = ModelBundle.load(first["xgboost"].bundle_dir)
    assert xgb.metadata["imbalance"]["strategy"] == SAMPLE_WEIGHT
    weights = xgb.metadata["imbalance"]["class_weights_on_train"]
    counts = xgb.metadata["training_data"]["class_counts"]
    total = sum(counts.values())
    for label, n in counts.items():  # sklearn's "balanced": n_samples / (n_classes * n_c)
        assert weights[label] == pytest.approx(total / (3 * n), abs=1e-4)
    assert xgb.metadata["imbalance"]["resampling"] == "none"


def test_sample_weights_are_passed_only_to_xgboost():
    y = np.array([0] * 8 + [1, 2])
    specs = default_specs()
    assert specs["logistic_regression"].fit_params(y) == {}
    assert specs["random_forest"].fit_params(y) == {}
    weights = specs["xgboost"].fit_params(y)["clf__sample_weight"]
    assert weights[0] == pytest.approx(10 / (3 * 8)) and weights[-1] == pytest.approx(10 / 3)
    assert specs["xgboost"].fit_params(y, imbalance=NO_WEIGHTING) == {}


def test_search_spaces_are_documented_per_model():
    specs = default_specs()
    assert specs["logistic_regression"].search == "grid"
    assert {"n_estimators", "max_depth", "min_samples_leaf"} <= set(specs["random_forest"].space)
    assert {"learning_rate", "n_estimators", "max_depth", "subsample"} <= set(
        specs["xgboost"].space
    )
    described = describe_space(specs["xgboost"].space)
    json.dumps(described)  # JSON-safe for the experiment log
    assert described["max_depth"] == {"distribution": "randint", "range": [2, 8]}
    assert described["subsample"]["range"] == [0.6, 1.0]


# --- the experiment log -----------------------------------------------------------


def test_experiment_log_is_append_only(trained):
    log_text = (trained["artifacts"] / "experiment_log.jsonl").read_text(encoding="utf-8")
    assert log_text.startswith(trained["log_after_first"])
    runs = ExperimentLog(trained["artifacts"] / "experiment_log.jsonl").runs()
    assert [r["run_id"] for r in runs] == [t.run_id for t in trained["runs"]]
    assert all(r["status"] == "success" for r in runs)


def test_experiment_log_records_every_trial(trained):
    run = ExperimentLog(trained["artifacts"] / "experiment_log.jsonl").run()
    specs = quick_specs()
    assert run["started"]["dataset"]["sha256"] == trained["data"].dataset_sha256
    assert run["started"]["dataset"]["test_rows_used"] == 0

    for family, spec in specs.items():
        trials = [t for t in run["trials"] if t["model_family"] == family]
        stages = [t["stage"] for t in trials]
        expected = spec.candidates
        assert stages.count("baseline") == 1
        assert stages.count("imbalance_ablation") == 1
        assert stages.count("tuning") == expected
        for trial in trials:
            assert trial["estimator_params"]
            assert len(trial["cv"]["metrics"]["f1_macro"]["folds"]) == FOLDS
            assert "recall_SEVERE_HEATWAVE" in trial["cv"]["metrics"]
        ablation = next(t for t in trials if t["stage"] == "imbalance_ablation")
        assert ablation["imbalance_strategy"] == NO_WEIGHTING

        selected = run["models"][family]["model_selected"]
        best = next(t for t in trials if t["stage"] == "tuning" and t["rank"] == 1)
        assert selected["best_params"] == best["search_params"]
        assert run["models"][family]["model_packaged"]["model_version"].startswith(family)


# --- the bundle contract ----------------------------------------------------------


def test_bundles_follow_the_artifact_contract(trained):
    first, _ = trained["results"]
    run_id = trained["runs"][0].run_id
    for family in MODEL_FAMILIES:
        bundle = ModelBundle.load(first[family].bundle_dir)
        meta = bundle.metadata
        assert bundle.version == f"{family}-{run_id}"
        assert bundle.feature_columns == list(FEATURE_COLUMNS)
        assert bundle.input_columns == [*FEATURE_COLUMNS, MONTH_COLUMN]
        assert bundle.class_labels == {0: "NORMAL", 1: "HEATWAVE", 2: "SEVERE_HEATWAVE"}
        assert meta["training_data"]["sha256"] == trained["data"].dataset_sha256
        assert meta["labeling_rule_version"] == "IMD-HW-DAILY-v1"
        expected_scale = "StandardScaler" if family == "logistic_regression" else "passthrough"
        assert meta["preprocessing"]["scale"] == expected_scale
        assert meta["validation"]["rows"] == 200
        assert meta["model_sha256"] and meta["library_versions"]["scikit-learn"]


def test_bundle_predicts_by_column_name(trained):
    bundle = ModelBundle.load(trained["results"][0]["random_forest"].bundle_dir)
    X_val, _ = trained["data"].xy("validation")
    expected = bundle.predict_proba(X_val)
    assert list(expected.columns) == ["NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"]
    assert np.allclose(expected.sum(axis=1), 1)

    shuffled = X_val[list(reversed(X_val.columns))].assign(region_id="mumbai")
    pd.testing.assert_frame_equal(bundle.predict_proba(shuffled), expected)
    assert set(bundle.predict(X_val)) <= {"NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"}
    assert (
        prediction_fingerprint(expected.to_numpy())
        == (bundle.metadata["reproducibility"]["prediction_fingerprint"])
    )
    with pytest.raises(KeyError, match="wind_ms"):
        bundle.predict_proba(X_val.drop(columns="wind_ms"))


def copy_bundle(source, target):
    target.mkdir(parents=True)
    for name in ("model.joblib", "bundle.json"):
        (target / name).write_bytes((source / name).read_bytes())
    return target


def edit_metadata(directory, change):
    path = directory / "bundle.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    change(meta)
    path.write_text(json.dumps(meta), encoding="utf-8")


def test_bundle_rejects_a_tampered_model_file(trained, tmp_path):
    bundle_dir = copy_bundle(trained["results"][0]["xgboost"].bundle_dir, tmp_path / "b")
    with (bundle_dir / "model.joblib").open("ab") as fh:
        fh.write(b"\0")
    with pytest.raises(BundleError, match="SHA-256"):
        ModelBundle.load(bundle_dir)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda m: m["feature_columns"].reverse(), "feature order"),
        (lambda m: m["input_columns"].reverse(), "input columns"),
        (lambda m: m["class_labels"].pop("2"), "classes"),
        (lambda m: m["library_versions"].update({"scikit-learn": "0.0"}), "library versions"),
        (lambda m: m["preprocessing"].update({"scale": "StandardScaler"}), "preprocessing"),
        (lambda m: m.update({"bundle_schema": 99}), "schema"),
    ],
)
def test_bundle_rejects_an_inconsistent_contract(trained, tmp_path, change, message):
    bundle_dir = copy_bundle(trained["results"][0]["random_forest"].bundle_dir, tmp_path / "b")
    edit_metadata(bundle_dir, change)
    with pytest.raises(BundleError, match=message):
        ModelBundle.load(bundle_dir)


def test_bundles_are_immutable(trained):
    bundle = ModelBundle.load(trained["results"][0]["logistic_regression"].bundle_dir)
    with pytest.raises(BundleError, match="immutable"):
        save_bundle(bundle.directory, bundle.pipeline, {})


# --- loading the dataset ----------------------------------------------------------


def test_load_rejects_a_dataset_that_does_not_match_its_manifest(tmp_path, criteria):
    path = write_small_dataset(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    with pytest.raises(ValueError, match="SHA-256"):
        load_training_data(path, criteria)


def test_load_rejects_a_different_labelling_rule(tmp_path, criteria):
    path = write_small_dataset(tmp_path)
    manifest_path = path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["labeling_rule_version"] = "IMD-HW-DAILY-v0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="rebuild the dataset"):
        load_training_data(path, criteria)


# --- the CLI ----------------------------------------------------------------------


def test_cli_run_summary_verify(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MODELING_DATASET_PATH", str(write_small_dataset(tmp_path / "data")))
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CV_FOLDS", str(FOLDS))
    monkeypatch.setenv("TRAINING_N_JOBS", "1")

    assert cli.main(["run", "--quick", "--models", "logistic_regression,xgboost"]) == 0
    out = capsys.readouterr().out
    assert "logistic_regression" in out and "xgboost" in out and "random_forest" not in out
    assert cli.main(["verify"]) == 0
    assert capsys.readouterr().out.count("ok ") == 2

    run_id = ExperimentLog(tmp_path / "artifacts" / "experiment_log.jsonl").run()["run_id"]
    bundle_dir = tmp_path / "artifacts" / "runs" / run_id / "xgboost"
    edit_metadata(
        bundle_dir, lambda m: m["reproducibility"].update({"prediction_fingerprint": "0"})
    )
    assert cli.main(["verify"]) == 1
    assert "FAIL xgboost" in capsys.readouterr().out
    assert cli.main(["summary", "--run", "no-such-run"]) == 2
