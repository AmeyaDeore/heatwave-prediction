"""Human-readable evaluation report (Part 05 §4), rendered from report.json only.

The justification paragraph is templated from the selection trace rather than
written by hand, so it always states the reasons that actually decided, and it
is regenerated identically from the same evidence.
"""

from heatwave_ml.evaluation.metrics import HEATWAVE, NORMAL, SEVERE

FAMILY_NAMES = {
    "logistic_regression": "Logistic Regression",
    "random_forest": "Random Forest",
    "xgboost": "XGBoost",
}


def _name(report: dict, version: str) -> str:
    return FAMILY_NAMES.get(report["candidates"][version]["model_family"], version)


def _pct(value: float) -> str:
    return f"{100 * value:.1f} %"


def _p50_p95(timing: dict | None) -> str:
    return "—" if not timing else f"{timing['p50_ms']:.1f} / {timing['p95_ms']:.1f} ms"


def _interval(bounds: list[float], digits: int = 4) -> str:
    return f"[{bounds[0]:.{digits}f}, {bounds[1]:.{digits}f}]"


def justification(report: dict) -> str:
    """One paragraph, referencing the criteria (Part 05 §3) that decided."""
    sel = report["selection"]
    cands = report["candidates"]
    policy = report["policy"]["version"]
    names = {v: _name(report, v) for v in cands}
    gate_failures = {v: g["failures"] for v, g in sel["gates"].items() if not g["passed"]}

    parts = []
    passed = [names[v] for v in cands if v not in gate_failures]
    if gate_failures:
        failed = "; ".join(f"{names[v]}: {', '.join(f)}" for v, f in gate_failures.items())
        parts.append(
            f"Under policy {policy}, {len(passed)} of {len(cands)} candidates passed the "
            f"hard gates ({failed})."
        )
    else:
        parts.append(
            f"Under policy {policy}, all {len(cands)} candidates passed the hard gates: none "
            "predicted a SEVERE_HEATWAVE day as NORMAL, all were calibrated within the "
            "top-label ECE limit, all fit the per-request latency budget, and all have an "
            "exact SHAP explainer."
        )
    if sel["selected"] is None:
        parts.append("No model is selected, so nothing can be promoted.")
        return " ".join(parts)

    tier = sel["quality_tier"]
    dropped = [v for v in sel["gates"] if v not in gate_failures and v not in tier["members"]]
    f1_best = tier["by_metric"]["f1_macro"]["best"]
    tier_names = ", ".join(names[v] for v in tier["members"])
    sentence = (
        f"On the primary signal (macro-F1 and accuracy), {names[f1_best]} scored the highest "
        f"macro-F1 ({cands[f1_best]['metrics']['f1_macro']:.4f})"
    )
    if dropped:
        why = []
        for v in dropped:
            lower = [
                f"{metric} ({d['difference']:+.4f}, 95 % CI {_interval(d['interval'])})"
                for metric, t in tier["by_metric"].items()
                for d in [t["vs_best"][v]]
                if not d["in_tier"]
            ]
            why.append(f"{names[v]} is significantly lower on {' and '.join(lower)}")
        sentence += f"; {'; '.join(why)}, so the quality tier is {tier_names}."
    else:
        sentence += f", but no candidate was significantly worse, so the tier is {tier_names}."
    parts.append(sentence)

    cost = sel["cost"]
    lowest = cost["lowest"]
    others = [v for v in tier["members"] if v != lowest]
    c = report["policy"]["settings"]["misclassification_cost"]
    n, h, s = 0, 1, 2  # cost columns: NORMAL, HEATWAVE, SEVERE_HEATWAVE (predicted)
    lowest_cost = cost["vs_lowest"][lowest]["cost"]
    lowest_recall = cands[lowest]["metrics"]["per_class"][SEVERE]["recall"]
    sentence = (
        f"Weighting errors by operational cost (a missed SEVERE_HEATWAVE day costs "
        f"{c[SEVERE][n]:g}, an under-graded one {c[SEVERE][h]:g}, a missed HEATWAVE "
        f"{c[HEATWAVE][n]:g}, a false alarm {c[NORMAL][h]:g}-{c[NORMAL][s]:g}), "
        f"{names[lowest]} has the lowest expected cost ({lowest_cost:.4f} per prediction, "
        f"SEVERE_HEATWAVE recall {lowest_recall:.3f})"
    )
    if others:
        sentence += "; " + "; ".join(
            f"{names[v]} costs {cost['vs_lowest'][v]['cost']:.4f} "
            f"({'not ' if cost['vs_lowest'][v]['equivalent'] else ''}significantly more, "
            f"95 % CI of the difference {_interval(cost['vs_lowest'][v]['interval'])})"
            for v in others
        )
    parts.append(sentence + ".")

    lat = sel["latency"]
    chosen = sel["selected"]
    if lat["applied"]:
        parts.append(
            f"Because {names[chosen]} is operationally equivalent on cost and "
            f"{lat['speedup_over_lowest_cost']:.1f}x faster per request (p95 "
            f"{cands[chosen]['latency']['request_p95_ms']:.1f} ms against "
            f"{cands[lowest]['latency']['request_p95_ms']:.1f} ms; the policy's threshold is "
            f"{lat['material_speedup']:g}x), the latency tie-break selects it."
        )
    elif len(lat["equivalent"]) > 1:
        parts.append(
            f"The cost-equivalent alternatives are not materially faster "
            f"({lat['speedup_over_lowest_cost']:.1f}x, below the policy's "
            f"{lat['material_speedup']:g}x), so latency does not change the choice."
        )
    m = cands[chosen]["metrics"]
    fm = m["failure_modes"]
    parts.append(
        f"{names[chosen]} ({chosen}) is therefore selected: accuracy {m['accuracy']:.4f}, "
        f"macro-F1 {m['f1_macro']:.4f}, SEVERE_HEATWAVE recall "
        f"{m['per_class'][SEVERE]['recall']:.3f} with {fm['severe_predicted_normal']} of "
        f"{fm['severe_rows']} severe days predicted NORMAL, top-label ECE "
        f"{cands[chosen]['calibration']['top_label']['ece']:.4f}, and a p95 request time of "
        f"{cands[chosen]['latency']['request_p95_ms']:.1f} ms with an exact "
        f"{cands[chosen]['latency']['explainer']} for Part 06."
    )
    disagree = [n for n, s in report["sensitivity"].items() if not s["agrees"]]
    if report["sensitivity"] and not disagree:
        parts.append(
            "The choice is unchanged under every alternative cost matrix in the sensitivity check."
        )
    elif disagree:
        parts.append(
            "Under the alternative cost matrices "
            + ", ".join(
                f"{n} → {names.get(report['sensitivity'][n]['selected'], 'none')}" for n in disagree
            )
            + " the choice would differ, so it depends on the cost weighting."
        )
    return " ".join(parts)


def _table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def render_markdown(report: dict) -> str:
    cands = report["candidates"]
    sel = report["selection"]
    ds = report["dataset"]
    pol = report["policy"]
    order = list(cands)
    selected = sel["selected"]

    def label(v):
        star = " **(selected)**" if v == selected else ""
        role = " *(current production)*" if cands[v]["role"] == "champion" else ""
        return f"{_name(report, v)}{star}{role}"

    lines = [
        f"# Model evaluation `{report['evaluation_id']}`",
        "",
        "Generated by `heatwave-evaluate run` from `report.json` in this directory. "
        "Re-derive every number except the timings with "
        f"`uv run heatwave-evaluate verify --evaluation {report['evaluation_id']}`.",
        "",
        f"- **Evaluated:** {report['evaluated_at']}, training run `{report['training_run']}`",
        f"- **Test split:** {ds['test_rows']} rows of `{ds['path']}` "
        f"(SHA-256 `{ds['sha256'][:12]}…`, rule `{ds['labeling_rule_version']}`, "
        f"split seed {ds['split_seed']}): "
        + ", ".join(f"{c} {n}" for c, n in ds["test_class_counts"].items()),
        f"- **Selection policy:** `{pol['path']}` {pol['version']}, "
        + (
            f"last changed in commit `{pol['last_commit'][:10]}` at {pol['committed_at']}"
            if pol["last_commit"]
            else "never committed"
        )
        + (" — **uncommitted changes**" if pol["uncommitted_changes"] else ""),
    ]
    if report.get("repeat"):
        lines.append(
            f"- **Repeat evaluation** of {', '.join(report['repeat']['previous_evaluations'])}: "
            f"{report['repeat']['reason']}"
        )
    lines += [f"- **Note:** {n}" for n in report.get("notes", [])]
    lines += [
        "",
        f"**Selected: {_name(report, selected) if selected else 'none'}**"
        + (f" (`{selected}`)" if selected else ""),
        "",
    ]

    lines += [
        "## 1. Comparison table",
        "",
        "Held-out test split. Precision, recall and F1 are macro averages (each class "
        "counts equally, so the rare classes are not hidden by NORMAL).",
        "",
    ]
    lines += _table(
        ["Model", "Accuracy", "Precision", "Recall", "F1 Score"],
        [
            [
                label(v),
                f"{m['accuracy']:.4f}",
                f"{m['precision_macro']:.4f}",
                f"{m['recall_macro']:.4f}",
                f"{m['f1_macro']:.4f}",
            ]
            for v in order
            for m in [cands[v]["metrics"]]
        ],
    )
    lines += ["", "Weighted averages (each class weighted by its test support):", ""]
    lines += _table(
        ["Model", "Precision", "Recall", "F1 Score"],
        [
            [
                _name(report, v),
                f"{m['precision_weighted']:.4f}",
                f"{m['recall_weighted']:.4f}",
                f"{m['f1_weighted']:.4f}",
            ]
            for v in order
            for m in [cands[v]["metrics"]]
        ],
    )

    lines += ["", "## 2. Justification", "", report["justification"], ""]

    lines += ["## 3. Per-class metrics", ""]
    rows = []
    for v in order:
        for cls, s in cands[v]["metrics"]["per_class"].items():
            rows.append(
                [
                    _name(report, v),
                    cls,
                    f"{s['precision']:.4f}",
                    f"{s['recall']:.4f}",
                    f"{s['f1']:.4f}",
                    s["support"],
                ]
            )
    lines += _table(["Model", "Class", "Precision", "Recall", "F1", "Support"], rows)

    lines += [
        "",
        "## 4. Confusion matrices",
        "",
        "Rows are the true class, columns the predicted class. The dangerous failure "
        "mode is SEVERE_HEATWAVE → NORMAL (no warning at all). SEVERE_HEATWAVE → "
        "HEATWAVE is a lower-severity miss: a warning is still issued.",
        "",
    ]
    for v in order:
        cm = cands[v]["metrics"]["confusion_matrix"]
        fm = cands[v]["metrics"]["failure_modes"]
        lines += [
            f"**{_name(report, v)}**: SEVERE → NORMAL **{fm['severe_predicted_normal']}**"
            f" of {fm['severe_rows']}, SEVERE → HEATWAVE {fm['severe_predicted_heatwave']},"
            f" HEATWAVE → NORMAL {fm['heatwave_predicted_normal']} of "
            f"{fm['heatwave_rows']}, false alarms {fm['normal_predicted_heatwave']} "
            f"(→ HEATWAVE) + {fm['normal_predicted_severe']} (→ SEVERE)",
            "",
        ]
        lines += _table(
            ["true \\ predicted", *cm["labels"]],
            [[cm["labels"][i], *row] for i, row in enumerate(cm["matrix"])],
        )
        lines.append("")

    lines += [
        "## 5. Calibration",
        "",
        'The UI shows the top-class probability as "confidence" (Part 12). ECE is the '
        "row-weighted gap between mean confidence and observed accuracy over "
        f"{report['policy']['settings']['calibration']['bins']} equal-width bins; MCE is "
        "the largest single-bin gap (noisy in sparse bins).",
        "",
    ]
    lines += _table(
        ["Model", "Mean confidence", "Accuracy", "Top-label ECE", "MCE", "Brier", "Log loss"],
        [
            [
                _name(report, v),
                f"{c['top_label']['mean_confidence']:.4f}",
                f"{c['top_label']['accuracy']:.4f}",
                f"{c['top_label']['ece']:.4f}",
                f"{c['top_label']['mce']:.4f}",
                f"{c['brier_score']:.4f}",
                f"{c['log_loss']:.4f}",
            ]
            for v in order
            for c in [cands[v]["calibration"]]
        ],
    )
    lines += ["", 'Top-label reliability ("when it says X %, how often is it right?"):', ""]
    for v in order:
        lines += [f"**{_name(report, v)}**", ""]
        lines += _table(
            ["Confidence bin", "Rows", "Mean confidence", "Observed accuracy", "Gap"],
            [
                [
                    f"({b['bin'][0]:.1f}, {b['bin'][1]:.1f}]",
                    b["rows"],
                    f"{b['mean_confidence']:.3f}",
                    f"{b['observed_frequency']:.3f}",
                    f"{b['gap']:.3f}",
                ]
                for b in cands[v]["calibration"]["top_label"]["bins"]
            ],
        )
        lines.append("")
    lines += [
        "Per-class (one-vs-rest) ECE: "
        + "; ".join(
            f"{_name(report, v)} "
            + ", ".join(
                f"{cls} {r['ece']:.4f}" for cls, r in cands[v]["calibration"]["per_class"].items()
            )
            for v in order
        ),
        "",
    ]

    lines += [
        "## 6. Inference latency",
        "",
        f"Machine: {report['machine']['processor']}, {report['machine']['cpu_count']} "
        f"logical CPUs, {report['machine']['platform']}. Timed through "
        "`ModelBundle.predict_proba` on training rows, with the candidates interleaved "
        "round-robin so they share the same machine conditions. One request = one row "
        "predicted + explained; its p95 is the sum of the two p95s (an upper bound). "
        "Absolute times are specific to this machine and its load; the ratios between "
        "models are the robust part. Re-benchmark on the serving host (Parts 07, 18).",
        "",
    ]
    lines += _table(
        [
            "Model",
            "Bundle size",
            "Load",
            "Predict 1 row p50 / p95",
            f"Predict {cands[order[0]]['latency']['predict_batch']['rows']} rows p50 / p95",
            "SHAP explainer",
            "Explain 1 row p50 / p95",
            "Request p95",
        ],
        [
            [
                _name(report, v),
                f"{lat['bundle_bytes'] / 1e6:.2f} MB",
                "—" if lat["load_ms"] is None else f"{lat['load_ms']:.0f} ms",
                _p50_p95(lat["predict_single_row"]),
                _p50_p95(lat["predict_batch"]),
                lat["explainer"] or "none",
                _p50_p95(lat["explain_single_row"]),
                f"**{lat['request_p95_ms']:.1f} ms**",
            ]
            for v in order
            for lat in [cands[v]["latency"]]
        ],
    )

    boot = cands[order[0]]["bootstrap"]
    lines += [
        "",
        "## 7. Uncertainty",
        "",
        f"{_pct(boot['confidence'])} paired-bootstrap intervals ({boot['resamples']} "
        "resamples of the test rows, the same resamples for every model). With "
        f"{ds['test_class_counts'].get(SEVERE, 0)} SEVERE_HEATWAVE test rows, one row is "
        f"{100 / max(ds['test_class_counts'].get(SEVERE, 1), 1):.1f} points of severe recall.",
        "",
    ]
    lines += _table(
        ["Model", "Macro-F1", "Accuracy", "SEVERE recall", "Expected cost"],
        [
            [
                _name(report, v),
                _interval(b["f1_macro"]),
                _interval(b["accuracy"]),
                _interval(b[f"recall_{SEVERE}"], 3),
                _interval(b["expected_cost"]),
            ]
            for v in order
            for b in [cands[v]["bootstrap"]]
        ],
    )

    lines += ["", "## 8. Selection trace", "", "**Step 1: gates**", ""]
    lines += _table(
        ["Model", "Passed", "Failures"],
        [
            [_name(report, v), "yes" if g["passed"] else "**no**", "; ".join(g["failures"]) or "—"]
            for v, g in sel["gates"].items()
        ],
    )
    if selected is not None:
        lines += [
            "",
            "**Step 2: quality tier** (difference to the best; in the tier unless "
            "the whole interval is below 0)",
            "",
        ]
        rows = []
        for metric, t in sel["quality_tier"]["by_metric"].items():
            for v, d in t["vs_best"].items():
                rows.append(
                    [
                        metric,
                        _name(report, v),
                        f"{d['difference']:+.4f}",
                        _interval(d["interval"]),
                        "yes" if d["in_tier"] else "**no**",
                    ]
                )
        lines += _table(["Metric", "Model", "Δ vs best", "95 % CI", "In tier"], rows)
        lines += [
            "",
            "**Step 3: operational cost** (mean cost per prediction; equivalent "
            "unless the whole interval of the difference is above 0)",
            "",
        ]
        lines += _table(
            ["Model", "Cost", "Δ vs lowest", "95 % CI", "Equivalent"],
            [
                [
                    _name(report, v),
                    f"{d['cost']:.4f}",
                    f"{d['difference']:+.4f}",
                    _interval(d["interval"]),
                    "yes" if d["equivalent"] else "no",
                ]
                for v, d in sel["cost"]["vs_lowest"].items()
            ],
        )
        lat = sel["latency"]
        lines += [
            "",
            f"**Step 4: latency tie-break.** Fastest cost-equivalent model: "
            f"{_name(report, lat['fastest'])}, {lat['speedup_over_lowest_cost']:.2f}x the "
            f"lowest-cost model's request p95 (threshold {lat['material_speedup']:g}x): "
            f"{'applied' if lat['applied'] else 'not applied'}.",
            "",
            f"**Decided by:** {sel['decided_by']}.",
            "",
        ]
    lines += ["**Sensitivity to the cost matrix**", ""]
    lines += _table(
        ["Cost matrix", "Would select", "Decided by", "Agrees"],
        [
            [
                "policy (" + report["policy"]["version"] + ")",
                _name(report, selected) if selected else "none",
                sel.get("decided_by", "—"),
                "—",
            ]
        ]
        + [
            [
                n,
                _name(report, s["selected"]) if s["selected"] else "none",
                s["decided_by"] or "—",
                "yes" if s["agrees"] else "**no**",
            ]
            for n, s in report["sensitivity"].items()
        ],
    )
    lines += ["", "## 9. Candidates", ""]
    lines += _table(
        ["Model version", "Role", "Bundle", "model.joblib SHA-256", "Test prediction fingerprint"],
        [
            [
                f"`{v}`",
                c["role"],
                f"`{c['bundle']}`",
                f"`{c['model_sha256'][:16]}…`",
                f"`{c['test_prediction_fingerprint'][:16]}…`",
            ]
            for v, c in cands.items()
        ],
    )
    return "\n".join(lines) + "\n"
