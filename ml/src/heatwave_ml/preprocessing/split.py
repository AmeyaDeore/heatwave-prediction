"""Stratified train / validation / test split.

Stratified on the risk class, so the rare HEATWAVE and SEVERE_HEATWAVE rows appear
in every split in the same proportion. The validation split is for Part 04's
tuning decisions; the test split stays untouched until Part 05's final evaluation.
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

TRAIN, VALIDATION, TEST = "train", "validation", "test"
SPLITS = (TRAIN, VALIDATION, TEST)


def stratified_split(
    labels: pd.Series, test_fraction: float, validation_fraction: float, seed: int
) -> pd.Series:
    """Return a split name per row, aligned to ``labels.index``."""
    positions = np.arange(len(labels))
    rest, test = train_test_split(
        positions, test_size=test_fraction, stratify=labels, random_state=seed
    )
    train, validation = train_test_split(
        rest,
        test_size=validation_fraction / (1 - test_fraction),
        stratify=labels.iloc[rest],
        random_state=seed,
    )
    split = np.empty(len(labels), dtype=object)
    split[train], split[validation], split[test] = TRAIN, VALIDATION, TEST
    return pd.Series(split, index=labels.index, name="split")


def class_distribution(frame: pd.DataFrame, target: str, classes, by: str | None = None) -> dict:
    """Counts and shares per class, overall or per group (e.g. per split)."""

    def summarise(labels: pd.Series) -> dict:
        counts = labels.value_counts().reindex(classes, fill_value=0)
        return {
            "rows": int(len(labels)),
            "counts": {c: int(n) for c, n in counts.items()},
            "share": {c: round(float(n) / max(len(labels), 1), 4) for c, n in counts.items()},
        }

    if by is None:
        return summarise(frame[target])
    return {name: summarise(frame.loc[frame[by] == name, target]) for name in SPLITS}
