"""The model selection policy (config/model_selection.yaml) and the selection itself.

``select`` is a pure function of the evidence and the policy, so an evaluation
report can be re-derived (``heatwave-evaluate verify``) and the same evidence can
be re-run under alternative cost matrices (the sensitivity check).

    1. gates           dangerous miss count, top-label ECE, p95 request time, exact SHAP
    2. quality tier    not significantly worse than the best on macro-F1 or accuracy
    3. cost            lowest mean misclassification cost in the tier
    4. latency         a materially faster model with equivalent cost wins
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from heatwave_ml.evaluation.metrics import expected_cost, interval, scores_from_confusion


@dataclass(frozen=True)
class SelectionPolicy:
    version: str
    max_severe_predicted_normal: int
    max_top_label_ece: float
    max_p95_request_ms: float
    require_exact_shap_explainer: bool
    tier_metrics: tuple[str, ...]
    costs: np.ndarray
    material_speedup: float
    sensitivity: dict[str, np.ndarray]
    bootstrap_resamples: int
    bootstrap_confidence: float
    bootstrap_seed: int
    calibration_bins: int
    latency: dict
    raw: dict

    @classmethod
    def load(cls, path: Path, classes: tuple[str, ...]) -> "SelectionPolicy":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        def matrix(spec: dict, name: str) -> np.ndarray:
            if list(spec) != list(classes):
                raise ValueError(f"{path}: {name} rows must be {list(classes)} in that order")
            if any(len(spec[c]) != len(classes) for c in classes):
                raise ValueError(f"{path}: {name} must be {len(classes)}x{len(classes)}")
            m = np.array([spec[c] for c in classes], dtype=float)
            if (m < 0).any() or np.diag(m).any():
                raise ValueError(f"{path}: {name} needs non-negative costs and a zero diagonal")
            return m

        gates, tier = raw["gates"], raw["quality_tier"]
        unknown = set(tier["metrics"]) - {"f1_macro", "accuracy"}
        if unknown:
            raise ValueError(f"{path}: unsupported quality_tier metrics {sorted(unknown)}")
        if not 0 < raw["bootstrap"]["confidence"] < 1:
            raise ValueError(f"{path}: bootstrap.confidence must be in (0, 1)")
        if raw["latency_tiebreak"]["material_speedup"] < 1:
            raise ValueError(f"{path}: latency_tiebreak.material_speedup must be >= 1")
        return cls(
            version=raw["policy_version"],
            max_severe_predicted_normal=int(gates["max_severe_predicted_normal"]),
            max_top_label_ece=float(gates["max_top_label_ece"]),
            max_p95_request_ms=float(gates["max_p95_request_ms"]),
            require_exact_shap_explainer=bool(gates["require_exact_shap_explainer"]),
            tier_metrics=tuple(tier["metrics"]),
            costs=matrix(raw["misclassification_cost"], "misclassification_cost"),
            material_speedup=float(raw["latency_tiebreak"]["material_speedup"]),
            sensitivity={
                name: matrix(spec, f"cost_sensitivity.{name}")
                for name, spec in (raw.get("cost_sensitivity") or {}).items()
            },
            bootstrap_resamples=int(raw["bootstrap"]["resamples"]),
            bootstrap_confidence=float(raw["bootstrap"]["confidence"]),
            bootstrap_seed=int(raw["bootstrap"]["seed"]),
            calibration_bins=int(raw["calibration"]["bins"]),
            latency=dict(raw["latency"]),
            raw=raw,
        )


@dataclass(frozen=True, eq=False)  # compared by identity: fields hold numpy arrays
class Evidence:
    """What the selection needs to know about one candidate."""

    version: str
    confusion: np.ndarray  # (k, k) on the test split
    boot_confusion: np.ndarray  # (resamples, k, k), paired across candidates
    severe_predicted_normal: int
    top_label_ece: float
    p95_request_ms: float
    exact_shap_explainer: bool


def _gates(ev: Evidence, policy: SelectionPolicy) -> list[str]:
    failures = []
    if ev.severe_predicted_normal > policy.max_severe_predicted_normal:
        failures.append(
            f"{ev.severe_predicted_normal} SEVERE_HEATWAVE rows predicted NORMAL "
            f"(max {policy.max_severe_predicted_normal})"
        )
    if ev.top_label_ece > policy.max_top_label_ece:
        failures.append(f"top-label ECE {ev.top_label_ece:.4f} > {policy.max_top_label_ece}")
    if ev.p95_request_ms > policy.max_p95_request_ms:
        failures.append(
            f"p95 request {ev.p95_request_ms:.1f} ms > {policy.max_p95_request_ms:g} ms"
        )
    if policy.require_exact_shap_explainer and not ev.exact_shap_explainer:
        failures.append("no exact SHAP explainer for this model type")
    return failures


def _paired_difference(a: Evidence, b: Evidence, values, confidence: float) -> dict:
    """``values(ev)`` → (point, samples). Difference a − b with its interval."""
    point_a, samples_a = values(a)
    point_b, samples_b = values(b)
    return {
        "difference": round(float(point_a - point_b), 5),
        "interval": interval(samples_a - samples_b, confidence),
    }


def select(
    evidence: list[Evidence], policy: SelectionPolicy, costs: np.ndarray | None = None
) -> dict:
    """Apply steps 1-4. Ties always go to the earlier candidate in ``evidence``."""
    costs = policy.costs if costs is None else costs
    confidence = policy.bootstrap_confidence
    trace: dict = {"gates": {}, "selected": None}

    def metric(name):
        def values(ev):
            return (
                scores_from_confusion(ev.confusion)[name],
                scores_from_confusion(ev.boot_confusion)[name],
            )

        return values

    def cost(ev):
        return expected_cost(ev.confusion, costs), expected_cost(ev.boot_confusion, costs)

    # 1. Gates.
    for ev in evidence:
        failures = _gates(ev, policy)
        trace["gates"][ev.version] = {"passed": not failures, "failures": failures}
    eligible = [ev for ev in evidence if trace["gates"][ev.version]["passed"]]
    if not eligible:
        trace["rationale"] = "No candidate passed the gates; nothing can be selected."
        return trace

    # 2. Quality tier: drop a candidate only if it is significantly worse than the best.
    tier_trace, tier = {}, list(eligible)
    for name in policy.tier_metrics:
        best = max(eligible, key=lambda ev, name=name: metric(name)(ev)[0])
        comparisons = {}
        for ev in eligible:
            diff = _paired_difference(ev, best, metric(name), confidence)
            diff["in_tier"] = ev is best or diff["interval"][1] >= 0
            comparisons[ev.version] = diff
            if not diff["in_tier"] and ev in tier:
                tier.remove(ev)
        tier_trace[name] = {"best": best.version, "vs_best": comparisons}
    trace["quality_tier"] = {"members": [ev.version for ev in tier], "by_metric": tier_trace}

    # 3. Lowest operational cost in the tier.
    lowest = min(tier, key=lambda ev: cost(ev)[0])
    cost_trace, equivalent = {}, []
    for ev in tier:
        diff = _paired_difference(ev, lowest, cost, confidence)
        diff["cost"] = round(float(cost(ev)[0]), 5)
        diff["equivalent"] = ev is lowest or diff["interval"][0] <= 0
        cost_trace[ev.version] = diff
        if diff["equivalent"]:
            equivalent.append(ev)
    trace["cost"] = {"lowest": lowest.version, "vs_lowest": cost_trace}

    # 4. Latency tie-break among cost-equivalent candidates.
    fastest = min(equivalent, key=lambda ev: ev.p95_request_ms)
    speedup = lowest.p95_request_ms / fastest.p95_request_ms if fastest.p95_request_ms else 1.0
    use_fastest = fastest is not lowest and speedup >= policy.material_speedup
    selected = fastest if use_fastest else lowest
    trace["latency"] = {
        "equivalent": [ev.version for ev in equivalent],
        "fastest": fastest.version,
        "speedup_over_lowest_cost": round(float(speedup), 2),
        "material_speedup": policy.material_speedup,
        "applied": use_fastest,
    }
    trace["selected"] = selected.version
    trace["decided_by"] = (
        "latency tie-break (step 4)"
        if use_fastest
        else "sole eligible candidate"
        if len(eligible) == 1
        else "lowest operational cost (step 3)"
    )
    return trace
