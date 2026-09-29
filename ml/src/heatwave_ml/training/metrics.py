"""Scoring used during tuning (CV on the training split) and on the validation split.

Macro-F1 is the tuning objective. Accuracy alone would reward "always NORMAL",
which scores 81 % (docs/data/preprocessing.md §6). Per-class recall is logged
for every trial, because Part 05 weights SEVERE_HEATWAVE recall most heavily.
The test split is never scored here; that is Part 05's job, once.
"""

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
    make_scorer,
    precision_recall_fscore_support,
    recall_score,
)

REFIT_METRIC = "f1_macro"


def cv_scoring(class_labels: dict[int, str]) -> dict:
    """Scorer name → sklearn scorer. Higher is better for all of them."""
    scoring = {
        "f1_macro": "f1_macro",
        "accuracy": "accuracy",
        "balanced_accuracy": "balanced_accuracy",
        "f1_weighted": "f1_weighted",
        "precision_macro": "precision_macro",
        "recall_macro": "recall_macro",
        "neg_log_loss": "neg_log_loss",
    }
    for index, label in class_labels.items():
        scoring[f"recall_{label}"] = make_scorer(
            recall_score, labels=[index], average="macro", zero_division=0
        )
        scoring[f"f1_{label}"] = make_scorer(
            f1_score, labels=[index], average="macro", zero_division=0
        )
    return scoring


def summarise_cv(cv_results: dict, scoring: dict, index: int | None = None) -> dict:
    """Mean, std and per-fold scores for one candidate.

    Accepts either ``cross_validate`` output (``index=None``) or a search's
    ``cv_results_`` (``index`` = the candidate's row).
    """
    out = {}
    for name in scoring:
        if index is None:
            folds = np.asarray(cv_results[f"test_{name}"], dtype=float)
        else:
            n_folds = 0
            while f"split{n_folds}_test_{name}" in cv_results:
                n_folds += 1
            folds = np.array(
                [cv_results[f"split{i}_test_{name}"][index] for i in range(n_folds)], dtype=float
            )
        # Report log loss as a positive number (sklearn negates it so higher = better).
        key, sign = ("log_loss", -1.0) if name == "neg_log_loss" else (name, 1.0)
        folds = sign * folds
        out[key] = {
            "mean": round(float(folds.mean()), 5),
            "std": round(float(folds.std()), 5),
            "folds": [round(float(v), 5) for v in folds],
        }
    return out


def holdout_report(y_true, proba: np.ndarray, class_labels: dict[int, str]) -> dict:
    """Metrics on a held-out split (the validation split in Part 04)."""
    indices = sorted(class_labels)
    y_pred = np.asarray(indices)[proba.argmax(axis=1)]
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=indices, zero_division=0
    )
    return {
        "rows": int(len(y_true)),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 5),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 5),
        "f1_macro": round(float(f1_score(y_true, y_pred, average="macro")), 5),
        "f1_weighted": round(float(f1_score(y_true, y_pred, average="weighted")), 5),
        "log_loss": round(float(log_loss(y_true, proba, labels=indices)), 5),
        "per_class": {
            class_labels[i]: {
                "precision": round(float(p), 5),
                "recall": round(float(r), 5),
                "f1": round(float(f), 5),
                "support": int(s),
            }
            for i, p, r, f, s in zip(indices, precision, recall, f1, support, strict=True)
        },
        "confusion_matrix": {
            "labels": [class_labels[i] for i in indices],
            "rows_are": "true class",
            "matrix": confusion_matrix(y_true, y_pred, labels=indices).tolist(),
        },
    }
