"""Inference latency (Part 05 §3.4) and a preview of explanation cost (§3.5).

Timed through ``ModelBundle.predict_proba``, exactly the call the API will make,
so the numbers include column selection and the imputer, not only the estimator.
The explanation preview uses the exact SHAP explainer for the model type, as Part 06
will. Rows come from the training split: the benchmark never reads the test split.

Timings depend on the machine and on its state at the time (on a laptop on battery,
Windows throttles background processes several-fold), so candidates are timed
interleaved, the machine is recorded, and timings are not part of what
``heatwave-evaluate verify`` re-derives.
"""

import gc
import os
import platform
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

from heatwave_ml.bundle import ModelBundle

TREE, LINEAR = "TreeExplainer", "LinearExplainer"
EXACT_EXPLAINERS = {RandomForestClassifier: TREE, XGBClassifier: TREE, LogisticRegression: LINEAR}


def explainer_kind(bundle: ModelBundle) -> str | None:
    """The exact SHAP explainer for this estimator, or None if there isn't one."""
    return EXACT_EXPLAINERS.get(type(bundle.pipeline.named_steps["clf"]))


def machine() -> dict:
    return {
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }


def _summary(times: list[float]) -> dict:
    ms = np.asarray(times) * 1000
    return {
        "repeats": len(ms),
        "p50_ms": round(float(np.median(ms)), 3),
        "p95_ms": round(float(np.percentile(ms, 95)), 3),
        "mean_ms": round(float(ms.mean()), 3),
    }


def _interleaved(calls: dict[str, tuple], warmup: int, repeats: int) -> dict[str, dict]:
    """Time every candidate's call round-robin, rotating the order each round.

    Timing the models one after another would let a change in machine state (a
    virus scan, power throttling on battery, thermal limits) land on one model
    only. Interleaved, every model sees the same conditions, so their ratio, which
    the latency tie-break uses, stays fair even when absolute times drift.
    ``calls`` maps name -> (function, list of arguments to cycle through).
    """
    names = list(calls)
    for i in range(warmup):
        for name in names:
            fn, args = calls[name]
            fn(args[i % len(args)])
    times: dict[str, list[float]] = {name: [] for name in names}
    gc_was_enabled = gc.isenabled()
    gc.disable()  # a collection pause belongs to no model in particular
    try:
        for i in range(repeats):
            shift = i % len(names)
            for name in names[shift:] + names[:shift]:
                fn, args = calls[name]
                started = time.perf_counter()
                fn(args[i % len(args)])
                times[name].append(time.perf_counter() - started)
    finally:
        if gc_was_enabled:
            gc.enable()
    return {name: _summary(t) for name, t in times.items()}


def _explainer(bundle: ModelBundle, kind: str, background: pd.DataFrame):
    import shap  # imported lazily: slow, and only the benchmark needs it here

    pre, clf = bundle.pipeline.named_steps["pre"], bundle.pipeline.named_steps["clf"]
    if kind == TREE:
        explainer = shap.TreeExplainer(clf)
    else:
        explainer = shap.LinearExplainer(clf, pre.transform(background[bundle.input_columns]))

    def explain(row: pd.DataFrame):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return explainer.shap_values(pre.transform(row[bundle.input_columns]))

    return explain


def benchmark(bundles: list[ModelBundle], rows: pd.DataFrame, settings: dict) -> dict[str, dict]:
    """Per model version: single-row and batch prediction time, explanation time,
    and the request p95 the policy gates on.

    ``request_p95_ms`` = p95(predict one row) + p95(explain one row): an upper
    bound on the p95 of one live request.
    """
    warmup = int(settings["warmup"])
    singles = [rows.iloc[[i]] for i in range(min(len(rows), 50))]
    batch_rows = int(settings["batch_rows"])
    batches = [rows.iloc[i : i + batch_rows] for i in range(0, batch_rows * 5, batch_rows)]
    background = rows.sample(min(len(rows), int(settings["shap_background_rows"])), random_state=0)

    predict_single = _interleaved(
        {b.version: (b.predict_proba, singles) for b in bundles},
        warmup,
        int(settings["single_row_repeats"]),
    )
    predict_batch = _interleaved(
        {b.version: (b.predict_proba, batches) for b in bundles},
        warmup,
        int(settings["batch_repeats"]),
    )
    kinds = {b.version: explainer_kind(b) for b in bundles}
    explain = _interleaved(
        {
            b.version: (_explainer(b, kinds[b.version], background), singles)
            for b in bundles
            if kinds[b.version] is not None
        },
        min(warmup, 3),
        int(settings["explain_repeats"]),
    )

    results = {}
    for b in bundles:
        explained = explain.get(b.version)
        results[b.version] = {
            "bundle_bytes": sum(f.stat().st_size for f in b.directory.iterdir()),
            "predict_single_row": predict_single[b.version],
            "predict_batch": {"rows": batch_rows, **predict_batch[b.version]},
            "explainer": kinds[b.version],
            "explain_single_row": explained,
            "request_p95_ms": round(
                predict_single[b.version]["p95_ms"] + (explained["p95_ms"] if explained else 0), 3
            ),
        }
    return results
