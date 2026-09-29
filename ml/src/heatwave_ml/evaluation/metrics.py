"""Test-split metrics (Part 05 §2): per-class and aggregate scores, the dangerous
failure mode, calibration, operational cost and paired bootstrap resamples.

Everything that the selection compares is computed from confusion matrices, so
one function serves both the point estimate and every bootstrap resample. The
aggregate scores are cross-checked against scikit-learn in the tests.
"""

import numpy as np
from sklearn.metrics import log_loss, precision_recall_fscore_support

from heatwave_ml.training.metrics import holdout_report

NORMAL, HEATWAVE, SEVERE = "NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"


def _round(value: float) -> float:
    return round(float(value), 5)


def confusion(y_true: np.ndarray, y_pred: np.ndarray, k: int) -> np.ndarray:
    """k x k counts, rows = true class, columns = predicted class."""
    return np.bincount(y_true * k + y_pred, minlength=k * k).reshape(k, k)


def _safe_divide(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    return np.divide(num, den, out=np.zeros_like(num, dtype=float), where=den > 0)


def scores_from_confusion(matrix: np.ndarray) -> dict[str, np.ndarray]:
    """Accuracy, macro-F1 and per-class recall for one (k, k) matrix or a stack (..., k, k).

    Zero division scores 0, as in scikit-learn with ``zero_division=0``.
    """
    matrix = np.asarray(matrix, dtype=float)
    diag = np.diagonal(matrix, axis1=-2, axis2=-1)
    total = matrix.sum(axis=(-2, -1))
    recall = _safe_divide(diag, matrix.sum(axis=-1))
    precision = _safe_divide(diag, matrix.sum(axis=-2))
    f1 = _safe_divide(2 * precision * recall, precision + recall)
    return {
        "accuracy": diag.sum(axis=-1) / total,
        "f1_macro": f1.mean(axis=-1),
        "recall": recall,
    }


def expected_cost(matrix: np.ndarray, costs: np.ndarray) -> np.ndarray:
    """Mean misclassification cost per prediction, for one matrix or a stack."""
    matrix = np.asarray(matrix, dtype=float)
    return (matrix * costs).sum(axis=(-2, -1)) / matrix.sum(axis=(-2, -1))


def classification_metrics(
    y_true: np.ndarray, proba: np.ndarray, class_labels: dict[int, str]
) -> dict:
    """Part 04's holdout report, plus macro and weighted precision/recall and the
    specific confusions an early-warning system cares about."""
    report = holdout_report(y_true, proba, class_labels)
    indices = sorted(class_labels)
    y_pred = np.asarray(indices)[proba.argmax(axis=1)]
    for average in ("macro", "weighted"):
        p, r, f, _ = precision_recall_fscore_support(
            y_true, y_pred, labels=indices, average=average, zero_division=0
        )
        report[f"precision_{average}"] = _round(p)
        report[f"recall_{average}"] = _round(r)
        report[f"f1_{average}"] = _round(f)

    index = {label: i for i, label in class_labels.items()}
    matrix = np.asarray(report["confusion_matrix"]["matrix"])
    n_severe = int(matrix[index[SEVERE]].sum())
    n_heatwave = int(matrix[index[HEATWAVE]].sum())
    report["failure_modes"] = {
        # The dangerous miss: no warning at all for the worst events.
        "severe_predicted_normal": int(matrix[index[SEVERE], index[NORMAL]]),
        # Under-graded: a warning is issued, but at the lower level.
        "severe_predicted_heatwave": int(matrix[index[SEVERE], index[HEATWAVE]]),
        "heatwave_predicted_normal": int(matrix[index[HEATWAVE], index[NORMAL]]),
        "severe_rows": n_severe,
        "heatwave_rows": n_heatwave,
        # False alarms, by the level of warning they would trigger.
        "normal_predicted_heatwave": int(matrix[index[NORMAL], index[HEATWAVE]]),
        "normal_predicted_severe": int(matrix[index[NORMAL], index[SEVERE]]),
    }
    return report


def _reliability(confidence: np.ndarray, correct: np.ndarray, bins: int) -> dict:
    """Equal-width reliability table, ECE (count-weighted gap) and MCE (largest gap)."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    # Bin i holds (edges[i], edges[i+1]]; a confidence of exactly 0 goes in bin 0.
    which = np.clip(np.searchsorted(edges, confidence, side="left") - 1, 0, bins - 1)
    table, ece, mce = [], 0.0, 0.0
    for i in range(bins):
        mask = which == i
        n = int(mask.sum())
        if n == 0:
            continue
        mean_conf, observed = float(confidence[mask].mean()), float(correct[mask].mean())
        gap = abs(mean_conf - observed)
        ece += gap * n / len(confidence)
        mce = max(mce, gap)
        table.append(
            {
                "bin": [_round(edges[i]), _round(edges[i + 1])],
                "rows": n,
                "mean_confidence": _round(mean_conf),
                "observed_frequency": _round(observed),
                "gap": _round(gap),
            }
        )
    return {"ece": _round(ece), "mce": _round(mce), "bins": table}


def calibration_metrics(
    y_true: np.ndarray, proba: np.ndarray, class_labels: dict[int, str], bins: int
) -> dict:
    """Is "91 % confidence" right about 91 % of the time? (Part 05 §2)

    ``top_label`` is the probability the UI shows as confidence: the top class's
    probability, against whether the top class was correct. ``per_class`` is the
    one-vs-rest view of each class's probability.
    """
    indices = sorted(class_labels)
    onehot = np.eye(len(indices))[y_true]
    top = proba.argmax(axis=1)
    top_label = _reliability(proba.max(axis=1), (top == y_true).astype(float), bins)
    top_label["mean_confidence"] = _round(proba.max(axis=1).mean())
    top_label["accuracy"] = _round((top == y_true).mean())
    return {
        "bins": bins,
        "brier_score": _round(((proba - onehot) ** 2).sum(axis=1).mean()),
        "log_loss": _round(log_loss(y_true, proba, labels=indices)),
        "top_label": top_label,
        "per_class": {
            class_labels[i]: _reliability(proba[:, i], onehot[:, i], bins) for i in indices
        },
    }


def bootstrap_confusions(
    y_true: np.ndarray, predictions: dict[str, np.ndarray], k: int, resamples: int, seed: int
) -> dict[str, np.ndarray]:
    """Paired bootstrap: the same resampled rows for every model, so differences
    between models are not blurred by independent resampling noise.

    Returns, per model, a (resamples, k, k) stack of confusion matrices.
    """
    n = len(y_true)
    rows = np.random.default_rng(seed).integers(0, n, size=(resamples, n))
    offsets = (np.arange(resamples) * k * k)[:, None]
    out = {}
    for name, y_pred in predictions.items():
        codes = y_true[rows] * k + y_pred[rows] + offsets
        out[name] = np.bincount(codes.ravel(), minlength=resamples * k * k).reshape(resamples, k, k)
    return out


def interval(samples: np.ndarray, confidence: float) -> list[float]:
    tail = (1 - confidence) / 2
    low, high = np.quantile(samples, [tail, 1 - tail])
    return [_round(low), _round(high)]
