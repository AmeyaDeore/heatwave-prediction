"""Part 06: the SHAP explainer, its per-prediction contract, the frozen artifact and the
registry link, the summary template, the shared label table, and the sanity checks."""

import json
import shutil

import numpy as np
import pandas as pd
import pytest
from test_training import make_trainer, write_small_dataset

from heatwave_ml.bundle import ModelBundle
from heatwave_ml.explainability import cli as explain_cli
from heatwave_ml.explainability.builder import (
    ExplainerBuilder,
    consistency,
    global_importance,
    sample_background,
)
from heatwave_ml.explainability.explainer import (
    BACKGROUND_FILE,
    LOG_ODDS,
    MANIFEST_FILE,
    ExplainerError,
    HeatwaveExplainer,
    explainer_dir,
    float32_floor,
    load_production_explainer,
    target_class,
)
from heatwave_ml.explainability.sanity import CASES, CHECKS, case_rows, run_sanity_checks
from heatwave_ml.explainability.settings import ExplainabilitySettings
from heatwave_ml.explainability.summary import format_probability, format_value, summarize
from heatwave_ml.features import FEATURE_COLUMNS, SeasonalNormals
from heatwave_ml.features.schema import (
    FEATURE_DISPLAY,
    FEATURE_LABELS,
    FEATURE_LABELS_FILE,
    RISK_CLASS_LABELS,
    load_feature_labels,
)
from heatwave_ml.ingestion.settings import REPO_ROOT
from heatwave_ml.registry import ModelRegistry
from heatwave_ml.training.trainer import load_training_data

FAMILIES = ("logistic_regression", "random_forest", "xgboost")
CONTRACT_KEYS = {"risk_class", "confidence", "probabilities", "explanation"}
FACTOR_KEYS = {
    "rank",
    "feature",
    "label",
    "unit",
    "value",
    "display_value",
    "imputed",
    "contribution",
    "share_pct",
    "direction",
}
REAL_NORMALS = REPO_ROOT / "config" / "seasonal_normals.csv"


@pytest.fixture(scope="module")
def trained(tmp_path_factory, criteria):
    """One quick training run: a bundle per family, on a small slice of the real data."""
    root = tmp_path_factory.mktemp("explainability")
    dataset = write_small_dataset(root / "data", poison_test=False)
    data = load_training_data(dataset, criteria)
    artifacts = root / "artifacts"
    trainer = make_trainer(data, artifacts)
    trainer.run()
    run_dir = artifacts / "runs" / trainer.run_id
    bundles = {family: ModelBundle.load(run_dir / family) for family in FAMILIES}
    return {
        "root": root,
        "dataset": dataset,
        "data": data,
        "artifacts": artifacts,
        "bundles": bundles,
    }


@pytest.fixture(scope="module")
def explainers(trained):
    background = sample_background(trained["data"].train, 60, seed=42)
    return {
        family: HeatwaveExplainer.build(bundle, background, source={"split": "train"}, seed=42)
        for family, bundle in trained["bundles"].items()
    }


@pytest.fixture(scope="module")
def rows(trained):
    return trained["data"].validation.head(40)


# --- the SHAP consistency property (Part 06 §7, Part 17 §2) -------------------------


@pytest.mark.parametrize("family", FAMILIES)
def test_shap_values_sum_to_the_model_output(explainers, rows, family):
    """Baseline + contributions = the model's raw output, for every class and row."""
    parts = explainers[family].contributions(rows)
    phi, ev, raw = parts["shap_values"], parts["expected_value"], parts["raw_output"]
    assert phi.shape == (len(rows), len(FEATURE_COLUMNS), 3)
    np.testing.assert_allclose(phi.sum(axis=1) + ev, raw, atol=1e-4)


@pytest.mark.parametrize("family", FAMILIES)
def test_explained_output_is_the_target_vs_normal_log_ratio(explainers, rows, family):
    explainer = explainers[family]
    parts = explainer.contributions(rows)
    for row, e in enumerate(explainer.explain(rows)):
        total = sum(f.contribution for f in e.factors)
        assert e.baseline + total == pytest.approx(e.output, abs=1e-3)
        p = e.probabilities
        if explainer.engine.quantity == LOG_ODDS:
            proba = parts["probabilities"][row]
            labels = explainer.labels
            expected = np.log(proba[labels.index(e.target_class)] / proba[labels.index("NORMAL")])
        else:  # Random Forest explains probabilities directly
            expected = p[e.target_class] - p["NORMAL"]
        assert e.output == pytest.approx(expected, abs=1e-3)


def test_float32_floor_keeps_sklearn_branching():
    """A float32 input goes left of the floored threshold exactly when sklearn sends it
    left of the float64 one. The case that broke Random Forest additivity: t between
    two adjacent float32 values, where nearest rounding lands on the upper one."""
    t = np.array([4.009999990463257, 38.29999923706055, -2.0, 1.5])
    floored = float32_floor(t)
    assert (floored <= t).all()
    assert (floored == floored.astype(np.float32).astype(np.float64)).all()
    x = np.float32(4.01)  # 4.010000228881836 > t[0]: sklearn sends it right
    assert float(x) > t[0] and np.float32(t[0]) == x  # nearest rounding would send it left
    assert float(x) > floored[0]
    assert list(floored[2:]) == [-2.0, 1.5]


@pytest.mark.parametrize("family", ("random_forest", "xgboost"))
def test_the_whole_background_is_used(trained, family):
    """SHAP silently subsamples a bare background of more than 100 rows. The baseline
    must be the mean output over exactly the frozen background, however large."""
    bundle = trained["bundles"][family]
    background = sample_background(trained["data"].train, 150, seed=3)
    explainer = HeatwaveExplainer.build(bundle, background, source={}, seed=3)
    engine = explainer.engine
    mean_output = engine.raw_output(engine.transform(background)).mean(axis=0)
    np.testing.assert_allclose(engine.expected_value, mean_output, atol=1e-5)


def test_consistency_check_passes_and_reports(explainers, rows):
    report = consistency(explainers["xgboost"], rows)
    assert report["passed"] and report["rows"] == len(rows)
    assert report["max_error_vs_bundle_proba"] == 0


@pytest.mark.parametrize("family", FAMILIES)
def test_prediction_is_exactly_the_bundles(explainers, trained, rows, family):
    explanations = explainers[family].explain(rows)
    expected = trained["bundles"][family].predict_proba(rows)
    assert [e.risk_class for e in explanations] == list(expected.idxmax(axis=1))
    for e, (_, probs) in zip(explanations, expected.iterrows(), strict=True):
        assert e.probabilities == {k: round(float(v), 4) for k, v in probs.items()}


# --- the output contract (Part 06 §3) -------------------------------------------------


def test_contract_shape_ranking_and_signs(explainers, rows):
    for e in explainers["xgboost"].explain(rows):
        d = e.to_dict()
        json.dumps(d)  # JSON-ready as is
        assert set(d) == CONTRACT_KEYS
        assert d["confidence"] == max(d["probabilities"].values())
        factors = d["explanation"]["factors"]
        assert [f["rank"] for f in factors] == list(range(1, len(FEATURE_COLUMNS) + 1))
        assert {f["feature"] for f in factors} == set(FEATURE_COLUMNS)
        assert all(set(f) == FACTOR_KEYS for f in factors)
        magnitudes = [abs(f["contribution"]) for f in factors]
        assert magnitudes == sorted(magnitudes, reverse=True)
        assert sum(abs(f["share_pct"]) for f in factors) == pytest.approx(100, abs=0.5)
        for f in factors:
            assert f["label"] == FEATURE_LABELS[f["feature"]]
            assert f["unit"] == FEATURE_DISPLAY[f["feature"]]["unit"]
            assert np.sign(f["share_pct"]) in (np.sign(f["contribution"]), 0)
            expected = {1: "increases_risk", -1: "decreases_risk", 0: "neutral"}
            assert f["direction"] == expected[int(np.sign(f["contribution"]))]
        assert d["explanation"]["summary"].startswith("The model predicts")


def test_target_rule():
    assert target_class("NORMAL") == "HEATWAVE"
    assert target_class("HEATWAVE") == "HEATWAVE"
    assert target_class("SEVERE_HEATWAVE") == "SEVERE_HEATWAVE"


def test_both_signs_occur_so_the_ui_can_be_tested(explainers, rows):
    """Part 12 §3 wants negative contributions rendered too: they are real, not rare."""
    directions = {f.direction for e in explainers["xgboost"].explain(rows) for f in e.factors}
    assert {"increases_risk", "decreases_risk"} <= directions


def test_missing_input_is_imputed_and_flagged(explainers, rows):
    explainer = explainers["xgboost"]
    row = rows.dropna(subset=list(FEATURE_COLUMNS)).head(1).copy()
    row["rh_pct"] = np.nan
    e = explainer.explain_one(row)
    rh = next(f for f in e.factors if f.feature == "rh_pct")
    month = int(row["month"].iloc[0])
    imputer = explainer.bundle.pipeline.named_steps["pre"].named_steps["impute"]
    assert rh.imputed and rh.value == round(imputer.monthly_medians_["rh_pct"][month], 2)
    assert not any(f.imputed for f in e.factors if f.feature != "rh_pct")


def test_explain_needs_every_input_column(explainers, rows):
    with pytest.raises(KeyError, match="month"):
        explainers["xgboost"].explain(rows.drop(columns="month"))
    with pytest.raises(ValueError, match="one row"):
        explainers["xgboost"].explain_one(rows.head(2))


def test_explanations_are_deterministic(explainers, rows):
    first = [e.to_dict() for e in explainers["xgboost"].explain(rows)]
    second = [e.to_dict() for e in explainers["xgboost"].explain(rows)]
    assert first == second


def test_global_importance_is_separate_and_ranked(explainers, rows):
    importance = global_importance(explainers["xgboost"].explain(rows))
    assert "not a per-prediction explanation" in importance["note"]
    values = [f["mean_abs_contribution"] for f in importance["features"]]
    assert values == sorted(values, reverse=True) and len(values) == len(FEATURE_COLUMNS)


# --- the frozen, versioned artifact (Part 06 §4, §8) ----------------------------------


def _saved(explainer, directory):
    explainer.save(directory)
    return directory


def test_save_and_load_round_trip(explainers, trained, rows, tmp_path):
    explainer = explainers["xgboost"]
    directory = _saved(explainer, tmp_path / "xgb")
    manifest = json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert (
        manifest["model"]["model_sha256"] == trained["bundles"]["xgboost"].metadata["model_sha256"]
    )
    assert manifest["explainer_id"].startswith(f"{explainer.model_version}+shap.")
    assert manifest["method"]["explainer"] == "TreeExplainer"
    assert manifest["method"]["feature_perturbation"] == "interventional"
    loaded = HeatwaveExplainer.load(directory, trained["bundles"]["xgboost"])
    assert [e.to_dict() for e in loaded.explain(rows)] == [
        e.to_dict() for e in explainer.explain(rows)
    ]


def test_explainer_choice_matches_the_model_type(explainers):
    assert explainers["xgboost"].engine.method == "TreeExplainer"
    assert explainers["random_forest"].engine.method == "TreeExplainer"
    assert explainers["logistic_regression"].engine.method == "LinearExplainer"


def test_load_refuses_an_explainer_built_for_another_model(explainers, trained, tmp_path):
    directory = _saved(explainers["xgboost"], tmp_path / "xgb")
    with pytest.raises(ExplainerError, match="Stale explainer"):
        HeatwaveExplainer.load(directory, trained["bundles"]["random_forest"])


def test_load_refuses_a_changed_background(explainers, trained, tmp_path):
    directory = _saved(explainers["xgboost"], tmp_path / "xgb")
    path = directory / BACKGROUND_FILE
    path.write_text(path.read_text(encoding="utf-8").replace(",", ";", 1), encoding="utf-8")
    with pytest.raises(ExplainerError, match="SHA-256"):
        HeatwaveExplainer.load(directory, trained["bundles"]["xgboost"])


def test_load_refuses_an_explainer_that_no_longer_reproduces(explainers, trained, tmp_path):
    directory = _saved(explainers["xgboost"], tmp_path / "xgb")
    path = directory / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["probe"]["shap_values"][0][0][0] += 0.01
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ExplainerError, match="does not reproduce"):
        HeatwaveExplainer.load(directory, trained["bundles"]["xgboost"])


def test_missing_explainer_is_a_clear_error(trained, tmp_path):
    with pytest.raises(ExplainerError, match="heatwave-explain build"):
        HeatwaveExplainer.load(tmp_path / "nothing", trained["bundles"]["xgboost"])


def _point_production_at(
    registry: ModelRegistry, bundle: ModelBundle, version: str | None = None
) -> None:
    registry.dir.mkdir(parents=True, exist_ok=True)
    registry.pointer_path.write_text(
        json.dumps(
            {
                "model_version": version or bundle.version,
                "model_family": bundle.family,
                "bundle": str(bundle.directory),
                "model_sha256": bundle.metadata["model_sha256"],
            }
        ),
        encoding="utf-8",
    )


def test_production_explainer_follows_the_pointer(explainers, trained, tmp_path):
    registry = ModelRegistry(tmp_path / "registry", trained["artifacts"] / "runs")
    xgb, rf = trained["bundles"]["xgboost"], trained["bundles"]["random_forest"]
    _point_production_at(registry, xgb)
    explainers["xgboost"].save(explainer_dir(registry, xgb.version))
    assert load_production_explainer(registry).model_version == xgb.version

    # A promotion to another model without a rebuild must fail loudly, not explain
    # the new model with the old explainer.
    _point_production_at(registry, rf)
    with pytest.raises(ExplainerError, match="No explainer"):
        load_production_explainer(registry)
    shutil.copytree(explainer_dir(registry, xgb.version), explainer_dir(registry, rf.version))
    with pytest.raises(ExplainerError, match="Stale explainer"):
        load_production_explainer(registry)


# --- the builder and the CLI -----------------------------------------------------------


def test_background_is_a_seeded_sample_of_train(trained):
    train = trained["data"].train
    first = sample_background(train, 50, seed=42)
    assert first.equals(sample_background(train, 50, seed=42))
    assert not first.equals(sample_background(train, 50, seed=7))
    assert set(first["record_id"]) <= set(train["record_id"])
    assert list(first["record_id"]) == sorted(first["record_id"])
    with pytest.raises(ExplainerError, match="Background"):
        sample_background(train, len(train) + 1, seed=42)


@pytest.fixture
def builder_settings(trained, tmp_path, monkeypatch):
    settings = ExplainabilitySettings(
        dataset_path=trained["dataset"],
        risk_config=REPO_ROOT / "config" / "risk_classes.yaml",
        seasonal_normals=REAL_NORMALS,
        selection_policy=REPO_ROOT / "config" / "model_selection.yaml",
        artifact_dir=trained["artifacts"],
        registry_dir=tmp_path / "registry",
        background_rows=40,
        seed=42,
    )
    registry = ModelRegistry(settings.registry_dir, settings.runs_dir)
    _point_production_at(registry, trained["bundles"]["xgboost"])
    # The quick test models are trained on 600 rows: the domain sanity checks are
    # asserted on the real production model below, not on these.
    monkeypatch.setattr(
        "heatwave_ml.explainability.builder.run_sanity_checks",
        lambda explainer, normals: [
            {"case": "stub", "expectation": "stub", "passed": True, "risk_class": "NORMAL"}
        ],
    )
    monkeypatch.setattr(
        "heatwave_ml.explainability.builder.BENCHMARK",
        {"warmup": 1, "single_row_repeats": 5, "batch_rows": 3, "batch_repeats": 2},
    )
    return settings


def test_builder_builds_logs_and_is_idempotent(builder_settings, trained):
    builder = ExplainerBuilder(builder_settings)
    result = builder.build(by="tester")
    assert result["status"] == "built"
    manifest = result["manifest"]
    assert manifest["background"]["rows"] == 40
    assert manifest["background"]["dataset_sha256"] == trained["data"].dataset_sha256
    assert manifest["checks"]["consistency"]["passed"]
    assert manifest["benchmark"]["passed"]
    events = builder.registry.events("explainer_built")
    assert events[-1]["explainer_id"] == manifest["explainer_id"] and events[-1]["by"] == "tester"

    assert builder.build(by="tester")["status"] == "unchanged"
    assert len(builder.registry.events("explainer_built")) == 1
    assert builder.verify() == []


def test_explainer_is_keyed_by_the_registered_version_not_the_bundles(builder_settings, trained):
    """On a fresh clone the bundle is rebuilt by a reproducible retrain: same SHA-256,
    new run id. The registry's version must stay the explainer's key and the version
    every explanation reports, or build/verify look in the wrong place and the API's
    model_version disagrees with its explainer_id."""
    builder = ExplainerBuilder(builder_settings)
    xgb = trained["bundles"]["xgboost"]
    _point_production_at(builder.registry, xgb, version="xgboost-registered")
    assert xgb.version != "xgboost-registered"

    result = builder.build(by="tester")
    assert result["directory"] == explainer_dir(builder.registry, "xgboost-registered")
    assert result["manifest"]["model"]["model_version"] == "xgboost-registered"
    assert builder.registry.events("explainer_built")[-1]["model_version"] == "xgboost-registered"
    assert builder.verify() == []

    explainer = load_production_explainer(builder.registry)
    assert explainer.model_version == "xgboost-registered"
    contract = explainer.explain(trained["data"].validation.head(1))[0].to_dict()["explanation"]
    assert contract["model_version"] == "xgboost-registered"
    assert contract["explainer_id"].startswith("xgboost-registered+shap.")


def test_builder_refuses_to_silently_replace_a_different_explainer(builder_settings):
    ExplainerBuilder(builder_settings).build(by="tester")
    changed = ExplainabilitySettings(**{**builder_settings.__dict__, "background_rows": 30})
    with pytest.raises(ExplainerError, match="--force"):
        ExplainerBuilder(changed).build(by="tester")
    assert ExplainerBuilder(changed).build(by="tester", force=True)["status"] == "built"
    assert ExplainerBuilder(changed).registry.events("explainer_built")[-1]["replaced"]


def test_builder_refuses_a_dataset_the_model_was_not_trained_on(builder_settings, tmp_path):
    other = write_small_dataset(tmp_path / "other", rows_per_split=(500, 200, 200))
    settings = ExplainabilitySettings(**{**builder_settings.__dict__, "dataset_path": other})
    with pytest.raises(ExplainerError, match="trained on"):
        ExplainerBuilder(settings).build(by="tester")


def test_cli_build_verify_show_explain(builder_settings, monkeypatch, capsys):
    for name, value in {
        "MODELING_DATASET_PATH": builder_settings.dataset_path,
        "MODEL_ARTIFACT_DIR": builder_settings.artifact_dir,
        "MODEL_REGISTRY_DIR": builder_settings.registry_dir,
        "SHAP_BACKGROUND_ROWS": builder_settings.background_rows,
    }.items():
        monkeypatch.setenv(name, str(value))
    assert explain_cli.main(["show"]) == 2  # nothing built yet
    assert explain_cli.main(["build", "--by", "tester"]) == 0
    assert explain_cli.main(["verify"]) == 0
    assert explain_cli.main(["show"]) == 0
    assert explain_cli.main(["explain", "--rows", "2", "--json"]) == 0
    out = capsys.readouterr().out
    assert "built:" in out and "ok   explainer loads" in out and '"explanation"' in out


# --- the summary sentence -----------------------------------------------------------------


def test_value_and_probability_formatting():
    assert format_value("tmax_c", 41.06) == "41.1 °C"
    assert format_value("temp_deviation_c", 7.44) == "+7.4 °C"
    assert format_value("temp_deviation_c", -0.74) == "-0.7 °C"
    assert format_value("rh_pct", 35.4) == "35%"
    assert format_value("wind_ms", 3.14) == "3.1 m/s"
    assert format_probability(0.9991) == ">99%"
    assert format_probability(0.004) == "<1%"
    assert format_probability(0.914) == "91%"


class F:
    def __init__(self, feature, contribution, share_pct, value):
        self.feature, self.label = feature, FEATURE_LABELS[feature]
        self.contribution, self.share_pct = contribution, share_pct
        self.direction = "increases_risk" if contribution > 0 else "decreases_risk"
        self.display_value = format_value(feature, value)


def test_summary_for_a_risk_prediction():
    factors = [
        F("temp_deviation_c", 3.0, 60.0, 7.4),
        F("tmax_c", 1.5, 30.0, 41.1),
        F("wind_ms", -0.4, -8.0, 5.0),
        F("rh_pct", 0.1, 2.0, 35.0),  # below the 5 % share floor: not named
    ]
    text = summarize("SEVERE_HEATWAVE", {"SEVERE_HEATWAVE": 0.91}, factors)
    assert text == (
        "The model predicts Severe Heatwave conditions (91% probability), mainly because of "
        "Temperature Deviation (+7.4 °C) and Maximum Temperature (41.1 °C). "
        "Wind Speed (5.0 m/s) partly offset the risk."
    )


def test_summary_for_a_normal_prediction():
    factors = [F("temp_deviation_c", -2.0, -70.0, -1.2), F("normal_tmax_c", 0.5, 20.0, 34.6)]
    text = summarize("NORMAL", {"NORMAL": 0.97}, factors)
    assert text == (
        "The model predicts Normal conditions (97% probability). The main factor keeping the "
        "risk low is Temperature Deviation (-1.2 °C). Seasonal Normal Temperature (34.6 °C) "
        "raised the risk somewhat."
    )


def test_summary_when_nothing_stands_out():
    factors = [F("rh_pct", -0.01, -3.0, 50.0)]
    assert summarize("HEATWAVE", {"HEATWAVE": 0.6}, factors).endswith("No single factor stood out.")


# --- the shared label table (Part 06 §5) --------------------------------------------------


def test_label_table_covers_every_feature_and_class():
    table = load_feature_labels()
    assert tuple(table["features"]) == FEATURE_COLUMNS
    assert set(RISK_CLASS_LABELS) == {"NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"}
    for spec in table["features"].values():
        assert {"label", "unit", "unit_detail", "decimals", "signed"} <= set(spec)


def test_label_table_rejects_drift(tmp_path):
    table = json.loads(FEATURE_LABELS_FILE.read_text(encoding="utf-8"))
    table["features"].pop("wind_ms")
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    with pytest.raises(ValueError, match="features must be exactly"):
        load_feature_labels(path)


# --- hand-picked sanity checks on the real production model (Part 06 §7, Part 17 §2) ------


@pytest.fixture(scope="module")
def production():
    registry = ModelRegistry(REPO_ROOT / "ml" / "registry", REPO_ROOT / "ml" / "artifacts" / "runs")
    try:
        return load_production_explainer(registry)
    except Exception as exc:  # bundles are git-ignored: absent on a fresh clone until retrained
        pytest.skip(f"production model or explainer not available here: {exc}")


def test_cases_go_through_the_live_feature_path():
    rows = case_rows(SeasonalNormals.load(REAL_NORMALS))
    assert len(rows) == len(CASES)
    assert list(rows.columns) == [*FEATURE_COLUMNS, "month"]
    deviation = rows["tmax_c"] - rows["normal_tmax_c"]
    np.testing.assert_allclose(deviation, rows["temp_deviation_c"], atol=0.051)
    assert rows["rh_pct"].isna().sum() == 1


def test_production_explainer_passes_every_sanity_check(production):
    results = run_sanity_checks(production, SeasonalNormals.load(REAL_NORMALS))
    assert len(results) == len(CHECKS)
    failed = [r for r in results if not r["passed"]]
    assert not failed, failed


def test_production_explainer_matches_its_recorded_build(production):
    manifest = production.manifest
    assert manifest["model"]["model_sha256"] == production.bundle.metadata["model_sha256"]
    assert all(c["passed"] for c in manifest["checks"]["sanity"])
    assert manifest["checks"]["consistency"]["passed"]
    top = manifest["checks"]["global_importance"]["features"][:2]
    assert {f["feature"] for f in top} == {"tmax_c", "temp_deviation_c"}


def test_production_explanation_of_an_extreme_day(production):
    rows = case_rows(SeasonalNormals.load(REAL_NORMALS))
    e = production.explain(rows.iloc[[0]])[0]  # extreme_heat
    d = e.to_dict()
    assert d["risk_class"] == "SEVERE_HEATWAVE"
    assert d["explanation"]["factors"][0]["feature"] in {"temp_deviation_c", "tmax_c"}
    assert d["explanation"]["summary"].startswith("The model predicts Severe Heatwave conditions")
    assert pd.notna(d["explanation"]["baseline"])
