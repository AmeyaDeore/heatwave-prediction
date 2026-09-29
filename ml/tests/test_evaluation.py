"""Part 05: test-split metrics, calibration, the selection policy, the evaluation
report and the model registry (production pointer, promotion, rollback)."""

import gc
import json
import shutil

import numpy as np
import pytest
import yaml
from sklearn.metrics import accuracy_score, f1_score, recall_score
from test_training import make_trainer, write_small_dataset

from heatwave_ml.bundle import ModelBundle
from heatwave_ml.evaluation import cli
from heatwave_ml.evaluation.evaluator import (
    CHAMPION,
    EvaluationError,
    Evaluator,
    policy_provenance,
)
from heatwave_ml.evaluation.latency import _interleaved
from heatwave_ml.evaluation.metrics import (
    bootstrap_confusions,
    calibration_metrics,
    confusion,
    expected_cost,
    scores_from_confusion,
)
from heatwave_ml.evaluation.policy import Evidence, SelectionPolicy, select
from heatwave_ml.evaluation.settings import EvaluationSettings
from heatwave_ml.features import TARGET_COLUMN, model_input
from heatwave_ml.ingestion.settings import REPO_ROOT
from heatwave_ml.preprocessing.dataset import load_modeling_dataset
from heatwave_ml.registry import ModelRegistry, RegistryError
from heatwave_ml.training.experiment_log import ExperimentLog
from heatwave_ml.training.trainer import load_training_data

POLICY_PATH = REPO_ROOT / "config" / "model_selection.yaml"
CLASSES = ("NORMAL", "HEATWAVE", "SEVERE_HEATWAVE")


@pytest.fixture(scope="module")
def policy():
    return SelectionPolicy.load(POLICY_PATH, CLASSES)


# --- metrics ------------------------------------------------------------------------


def test_confusion_scores_match_sklearn():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 3, 500)
    pred = np.where(rng.random(500) < 0.8, y, rng.integers(0, 3, 500))
    scores = scores_from_confusion(confusion(y, pred, 3))
    assert scores["accuracy"] == pytest.approx(accuracy_score(y, pred))
    assert scores["f1_macro"] == pytest.approx(f1_score(y, pred, average="macro"))
    assert scores["recall"] == pytest.approx(recall_score(y, pred, average=None))


def test_bootstrap_is_paired_seeded_and_complete():
    rng = np.random.default_rng(2)
    y = rng.integers(0, 3, 200)
    preds = {"a": y.copy(), "b": np.zeros_like(y)}
    first = bootstrap_confusions(y, preds, 3, 50, seed=7)
    second = bootstrap_confusions(y, preds, 3, 50, seed=7)
    assert first["a"].shape == (50, 3, 3)
    assert (first["a"] == second["a"]).all()
    assert (first["a"].sum(axis=(1, 2)) == 200).all()
    # Paired: both models see the same resampled rows, so the true-class counts agree.
    assert (first["a"].sum(axis=2) == first["b"].sum(axis=2)).all()
    # "a" is perfect in every resample.
    assert (scores_from_confusion(first["a"])["accuracy"] == 1).all()


def test_expected_cost_weights_errors_by_the_matrix(policy):
    perfect = np.diag([10, 5, 5])
    assert expected_cost(perfect, policy.costs) == 0
    missed_severe = np.array([[10, 0, 0], [0, 5, 0], [1, 0, 4]])
    false_alarm = np.array([[9, 1, 0], [0, 5, 0], [0, 0, 5]])
    assert expected_cost(missed_severe, policy.costs) == pytest.approx(20 / 20)
    assert expected_cost(false_alarm, policy.costs) == pytest.approx(1 / 20)


def test_calibration_detects_overconfidence():
    rng = np.random.default_rng(3)
    n = 4000
    y = rng.integers(0, 3, n)
    # Calibrated: the top class has probability 0.7 and is right 70 % of the time.
    correct = rng.random(n) < 0.7
    top = np.where(correct, y, (y + 1) % 3)
    calibrated = np.full((n, 3), 0.15)
    calibrated[np.arange(n), top] = 0.7
    good = calibration_metrics(y, calibrated, dict(enumerate(CLASSES)), bins=10)
    assert good["top_label"]["ece"] < 0.03
    # Overconfident: the same predictions, claimed at 0.98.
    overconfident = np.full((n, 3), 0.01)
    overconfident[np.arange(n), top] = 0.98
    bad = calibration_metrics(y, overconfident, dict(enumerate(CLASSES)), bins=10)
    assert bad["top_label"]["ece"] > 0.25
    assert sum(b["rows"] for b in bad["top_label"]["bins"]) == n


def test_calibration_puts_certain_predictions_in_the_last_bin():
    y = np.array([0, 1])
    proba = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    result = calibration_metrics(y, proba, dict(enumerate(CLASSES)), bins=10)
    assert result["top_label"]["bins"] == [
        {
            "bin": [0.9, 1.0],
            "rows": 2,
            "mean_confidence": 1.0,
            "observed_frequency": 1.0,
            "gap": 0.0,
        }
    ]


def test_latency_candidates_are_timed_interleaved():
    calls = []
    fns = {name: (lambda arg, name=name: calls.append(name), [None]) for name in "abc"}
    result = _interleaved(fns, warmup=1, repeats=3)
    assert calls == list("abc") + list("abc") + list("bca") + list("cab")
    assert all(r["repeats"] == 3 for r in result.values())
    assert gc.isenabled()


# --- the policy ---------------------------------------------------------------------


def test_committed_policy_loads(policy):
    assert policy.version == "SEL-v1"
    assert policy.max_severe_predicted_normal == 0
    assert policy.costs.shape == (3, 3)
    # The cost matrix encodes "a missed severe event costs more than a false alarm".
    assert policy.costs[2, 0] > policy.costs[1, 0] > policy.costs[0, 1]
    assert set(policy.sensitivity) == {"error_rate", "severe_dominant"}


@pytest.mark.parametrize(
    "path, value, message",
    [
        (("misclassification_cost", "NORMAL"), [1, 1, 2], "zero diagonal"),
        (("misclassification_cost", "HEATWAVE"), [5, 0], "3x3"),
        (("quality_tier", "metrics"), ["roc_auc"], "unsupported"),
        (("latency_tiebreak", "material_speedup"), 0.5, ">= 1"),
    ],
)
def test_invalid_policy_is_rejected(tmp_path, path, value, message):
    raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    raw[path[0]][path[1]] = value
    bad = tmp_path / "policy.yaml"
    bad.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        SelectionPolicy.load(bad, CLASSES)


Y = np.array([0] * 200 + [1] * 50 + [2] * 50)


def _with_errors(n_errors: int, true_class: int, predicted: int) -> np.ndarray:
    pred = Y.copy()
    rows = np.flatnonzero(true_class == Y)[:n_errors]
    pred[rows] = predicted
    return pred


def _evidence(predictions: dict, latency: dict | None = None, ece=None, explainer=None):
    boot = bootstrap_confusions(Y, predictions, 3, 500, seed=0)
    out = []
    for name, pred in predictions.items():
        matrix = confusion(Y, pred, 3)
        out.append(
            Evidence(
                version=name,
                confusion=matrix,
                boot_confusion=boot[name],
                severe_predicted_normal=int(matrix[2, 0]),
                top_label_ece=(ece or {}).get(name, 0.01),
                p95_request_ms=(latency or {}).get(name, 50.0),
                exact_shap_explainer=(explainer or {}).get(name, True),
            )
        )
    return out


def test_gates_exclude_the_dangerous_failure_mode(policy):
    evidence = _evidence(
        {
            "misses_one_severe": _with_errors(1, 2, 0),  # the best accuracy, but one SEVERE→NORMAL
            "under_grades": _with_errors(3, 2, 1),
        }
    )
    trace = select(evidence, policy)
    assert trace["gates"]["misses_one_severe"]["passed"] is False
    assert (
        "SEVERE_HEATWAVE rows predicted NORMAL"
        in trace["gates"]["misses_one_severe"]["failures"][0]
    )
    assert trace["selected"] == "under_grades"


def test_every_gate_is_applied(policy):
    evidence = _evidence(
        {"a": Y, "b": Y, "c": Y},
        latency={"b": 900.0},
        ece={"a": 0.2},
        explainer={"c": False},
    )
    trace = select(evidence, policy)
    assert [g["passed"] for g in trace["gates"].values()] == [False, False, False]
    assert "ECE" in trace["gates"]["a"]["failures"][0]
    assert "p95 request" in trace["gates"]["b"]["failures"][0]
    assert "SHAP" in trace["gates"]["c"]["failures"][0]
    assert trace["selected"] is None


def test_significantly_worse_quality_leaves_the_tier(policy):
    evidence = _evidence({"strong": _with_errors(2, 0, 1), "weak": _with_errors(60, 0, 1)})
    trace = select(evidence, policy)
    assert trace["quality_tier"]["members"] == ["strong"]
    assert trace["quality_tier"]["by_metric"]["f1_macro"]["vs_best"]["weak"]["in_tier"] is False
    assert trace["selected"] == "strong"


def test_operational_cost_decides_within_the_tier(policy):
    # Mirror-image mistakes: identical accuracy and macro-F1, but under-grading a
    # severe day (cost 3) is worse than over-grading a heatwave day (cost 1).
    evidence = _evidence(
        {"under_grades": _with_errors(15, 2, 1), "over_grades": _with_errors(15, 1, 2)},
        latency={"under_grades": 5.0, "over_grades": 100.0},  # speed must not rescue it
    )
    trace = select(evidence, policy)
    assert set(trace["quality_tier"]["members"]) == {"under_grades", "over_grades"}
    assert trace["cost"]["lowest"] == "over_grades"
    assert trace["cost"]["vs_lowest"]["under_grades"]["equivalent"] is False
    assert trace["selected"] == "over_grades"
    assert trace["decided_by"] == "lowest operational cost (step 3)"


@pytest.mark.parametrize("fast_ms, applied", [(10.0, True), (60.0, False)])
def test_latency_breaks_a_tie_only_when_material(policy, fast_ms, applied):
    same = _with_errors(4, 0, 1)
    evidence = _evidence(
        {"slow": same, "fast": same.copy()}, latency={"slow": 100.0, "fast": fast_ms}
    )
    trace = select(evidence, policy)
    assert trace["latency"]["applied"] is applied
    assert trace["selected"] == ("fast" if applied else "slow")


# --- end to end: evaluate, verify, promote, rollback ----------------------------------------


def _fast_policy(path):
    """The committed policy with fewer repeats. Gates are relaxed, because tiny
    quick-trained models on 200 test rows are not what the gates are sized for."""
    raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    raw["gates"] |= {"max_severe_predicted_normal": 1000, "max_top_label_ece": 1.0}
    raw["bootstrap"]["resamples"] = 200
    raw["latency"] |= {
        "warmup": 1,
        "single_row_repeats": 5,
        "batch_repeats": 3,
        "explain_repeats": 3,
        "shap_background_rows": 20,
    }
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def workspace(tmp_path_factory, criteria):
    """A quick-trained run (seed 42) and a differently seeded one (seed 7)."""
    root = tmp_path_factory.mktemp("evaluation")
    dataset = write_small_dataset(root / "data", poison_test=False)
    data = load_training_data(dataset, criteria)
    artifacts = root / "artifacts"
    first = make_trainer(data, artifacts)
    first.run()
    second = make_trainer(data, artifacts)
    second.seed = 7
    second.run()
    settings = EvaluationSettings(
        dataset_path=dataset,
        risk_config=REPO_ROOT / "config" / "risk_classes.yaml",
        selection_policy=_fast_policy(root / "model_selection.yaml"),
        artifact_dir=artifacts,
        registry_dir=root / "registry",
    )
    return {"settings": settings, "runs": (first.run_id, second.run_id), "root": root}


@pytest.fixture(scope="module")
def evaluated(workspace):
    evaluator = Evaluator(workspace["settings"])
    report = evaluator.run(workspace["runs"][0], allow_uncommitted_policy=True)
    return evaluator, report


def test_uncommitted_policy_is_refused(workspace):
    assert policy_provenance(workspace["settings"].selection_policy)["uncommitted_changes"]
    with pytest.raises(EvaluationError, match="uncommitted changes"):
        Evaluator(workspace["settings"]).run(workspace["runs"][0])


def test_report_scores_every_candidate_on_the_test_split(workspace, evaluated):
    _, report = evaluated
    test = load_modeling_dataset(workspace["settings"].dataset_path)["test"]
    y = test[TARGET_COLUMN].map({c: i for i, c in enumerate(CLASSES)}).to_numpy()
    assert report["dataset"]["test_rows"] == len(test) == 200
    assert len(report["candidates"]) == 3
    for c in report["candidates"].values():
        m = c["metrics"]
        assert sum(map(sum, m["confusion_matrix"]["matrix"])) == 200
        assert set(m["per_class"]) == set(CLASSES)
        for key in ("accuracy", "precision_macro", "recall_macro", "f1_macro", "f1_weighted"):
            assert 0 <= m[key] <= 1
        assert c["calibration"]["top_label"]["ece"] >= 0
        assert c["latency"]["request_p95_ms"] > 0
        assert c["latency"]["explainer"] in ("TreeExplainer", "LinearExplainer")
        lo, hi = c["bootstrap"]["f1_macro"]
        assert lo <= m["f1_macro"] <= hi
    # Scores agree with an independent sklearn computation on the same bundle.
    version, c = next(iter(report["candidates"].items()))
    bundle = ModelBundle.load(workspace["settings"].runs_dir / c["run_id"] / c["model_family"])
    pred = bundle.predict_proba(model_input(test)).to_numpy().argmax(axis=1)
    assert c["metrics"]["accuracy"] == pytest.approx(accuracy_score(y, pred), abs=1e-5)
    assert c["metrics"]["f1_macro"] == pytest.approx(f1_score(y, pred, average="macro"), abs=1e-5)


def test_report_is_written_with_a_justification(workspace, evaluated):
    _, report = evaluated
    directory = workspace["settings"].registry_dir / "evaluations" / report["evaluation_id"]
    assert json.loads((directory / "report.json").read_text(encoding="utf-8")) == report
    markdown = (directory / "report.md").read_text(encoding="utf-8")
    assert "| Model | Accuracy | Precision | Recall | F1 Score |" in markdown
    assert report["selection"]["selected"] is not None
    assert "is therefore selected" in report["justification"]
    assert report["policy"]["uncommitted_changes"] is True
    assert set(report["sensitivity"]) == {"error_rate", "severe_dominant"}


def test_the_same_comparison_is_scored_once(workspace, evaluated):
    evaluator, report = evaluated
    with pytest.raises(EvaluationError, match="already scored"):
        evaluator.run(workspace["runs"][0], allow_uncommitted_policy=True)
    assert len(evaluator.registry.events("evaluated")) == 1


def test_verify_re_derives_the_report(workspace, evaluated):
    evaluator, report = evaluated
    assert evaluator.verify(report["evaluation_id"]) == []
    # Tamper with a stored number: verify must notice.
    path = (
        workspace["settings"].registry_dir / "evaluations" / report["evaluation_id"] / "report.json"
    )
    original = path.read_text(encoding="utf-8")
    tampered = json.loads(original)
    first = next(iter(tampered["candidates"]))
    tampered["candidates"][first]["metrics"]["accuracy"] += 0.01
    path.write_text(json.dumps(tampered), encoding="utf-8")
    try:
        assert evaluator.verify(report["evaluation_id"]) == [
            f"{first}: metrics differs from the report"
        ]
    finally:
        path.write_text(original, encoding="utf-8")


def test_promote_rollback_and_the_pointer(workspace, evaluated):
    evaluator, report = evaluated
    registry = evaluator.registry
    selected = report["selection"]["selected"]
    others = [v for v in report["candidates"] if v != selected]

    with pytest.raises(RegistryError, match="give a --reason"):
        registry.promote(report["evaluation_id"], by="tester", model_version=others[0])

    pointer = registry.promote(report["evaluation_id"], by="tester")
    assert pointer["model_version"] == selected
    assert pointer["evaluation"]["selected_by_policy"] is True
    assert pointer["override"] is False and pointer["previous"] is None
    assert (
        pointer["evaluation"]["test_metrics"]["f1_macro"]
        == report["candidates"][selected]["metrics"]["f1_macro"]
    )
    bundle, loaded = registry.load_production()
    assert bundle.metadata["model_sha256"] == pointer["model_sha256"] and loaded == pointer
    with pytest.raises(RegistryError, match="already the production model"):
        registry.promote(report["evaluation_id"], by="tester")

    override = registry.promote(
        report["evaluation_id"], by="tester", model_version=others[0], reason="drill"
    )
    assert override["override"] is True and override["previous"] == selected

    back = registry.rollback(selected, by="tester", reason="drill over")
    assert back["action"] == "rollback" and back["model_version"] == selected
    with pytest.raises(RegistryError, match="never been evaluated"):
        registry.rollback("xgboost-19990101T000000Z-000000", by="tester", reason="x")

    assert [e["event"] for e in registry.events()] == [
        "evaluated",
        "promoted",
        "promoted",
        "rolled_back",
    ]
    statuses = {m["model_version"]: m["status"] for m in registry.models()}
    assert statuses[selected] == "production"
    assert all(statuses[v] == "archived" for v in others)  # archived, not deleted
    assert all(m["present"] for m in registry.models())


def test_a_gate_failure_cannot_be_promoted(workspace, evaluated):
    evaluator, report = evaluated
    registry = evaluator.registry
    failing = json.loads(json.dumps(report))
    failing["evaluation_id"] = "19990101T000000Z-gate00"
    victim = next(iter(failing["candidates"]))
    failing["selection"]["gates"][victim] = {"passed": False, "failures": ["synthetic failure"]}
    failing["comparison_key"] = "synthetic"
    registry.save_evaluation(failing, "synthetic")
    with pytest.raises(RegistryError, match="synthetic failure"):
        registry.promote(failing["evaluation_id"], by="tester", model_version=victim, reason="no")


def test_resolve_finds_a_reproduced_bundle_by_hash(workspace, evaluated, tmp_path):
    evaluator, _ = evaluated
    registry = evaluator.registry
    pointer = registry.production()
    runs = workspace["settings"].runs_dir
    moved = runs / "20991231T000000Z-rebuilt"
    shutil.copytree(runs / pointer["run_id"], moved)
    original = runs / pointer["run_id"]
    parked = tmp_path / "parked"
    shutil.move(original, parked)
    try:
        assert registry.resolve(pointer) == moved / pointer["model_family"]
    finally:
        shutil.move(parked, original)
        shutil.rmtree(moved)


def test_a_retrain_is_compared_with_the_production_champion(workspace, evaluated):
    evaluator, first = evaluated
    # A random forest is the champion: unlike lbfgs logistic regression, its model
    # depends on the seed, so the seed-7 retrain cannot reproduce it byte for byte.
    champion = next(
        v for v, c in first["candidates"].items() if c["model_family"] == "random_forest"
    )
    if evaluator.registry.production()["model_version"] != champion:
        evaluator.registry.promote(
            first["evaluation_id"], by="tester", model_version=champion, reason="champion test"
        )
    report = evaluator.run(workspace["runs"][1], allow_uncommitted_policy=True)
    roles = {v: c["role"] for v, c in report["candidates"].items()}
    assert roles[champion] == CHAMPION
    assert len(report["candidates"]) == 4
    assert evaluator.verify(report["evaluation_id"]) == []


def test_cli_evaluate_and_registry(workspace, monkeypatch, capsys):
    s = workspace["settings"]
    for name, value in {
        "MODELING_DATASET_PATH": s.dataset_path,
        "MODEL_ARTIFACT_DIR": s.artifact_dir,
        "MODEL_SELECTION_POLICY": s.selection_policy,
        "MODEL_REGISTRY_DIR": s.registry_dir.parent / "cli-registry",
    }.items():
        monkeypatch.setenv(name, str(value))
    run = workspace["runs"][0]
    assert cli.evaluate_main(["run", "--run", run]) == 2  # policy not committed
    assert cli.evaluate_main(["run", "--run", run, "--allow-uncommitted-policy"]) == 0
    assert "Selected:" in capsys.readouterr().out
    assert cli.evaluate_main(["run", "--run", run, "--allow-uncommitted-policy"]) == 2
    assert cli.evaluate_main(["verify"]) == 0
    assert cli.evaluate_main(["show"]) == 0
    evaluation_id = ModelRegistry(
        s.registry_dir.parent / "cli-registry", s.runs_dir
    ).evaluation_ids()[-1]
    assert cli.registry_main(["promote", "--evaluation", evaluation_id, "--by", "tester"]) == 0
    assert cli.registry_main(["status"]) == 0
    assert cli.registry_main(["verify"]) == 0
    out = capsys.readouterr().out
    assert "production:" in out and "production pointer resolves and loads" in out
    assert ExperimentLog(s.experiment_log).run(run)["status"] == "success"
