"""Build the modelling dataset (and its reference companions) from the raw landing zone.

    raw synthetic (Part 02 landing) → clean → build_features → label check → split
        → data/heatwave_dataset.csv + data/heatwave_dataset.manifest.json

Pure functions (``prepare_modeling_dataset`` etc.) take and return frames, so they
are testable without touching disk. The CLI (``cli.py``) does the reading and writing.
Part 04 reads the result with ``load_modeling_dataset``.
"""

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from heatwave_ml.features.criteria import RiskCriteria, classify
from heatwave_ml.features.engineering import build_features
from heatwave_ml.features.normals import SeasonalNormals
from heatwave_ml.features.schema import (
    FEATURE_COLUMNS,
    FEATURE_LABELS,
    FEATURE_UNITS,
    MONTH_COLUMN,
    SPLIT_COLUMN,
    TARGET_COLUMN,
)
from heatwave_ml.ingestion.regions import Region
from heatwave_ml.preprocessing.cleaning import clean
from heatwave_ml.preprocessing.split import SPLITS, class_distribution, stratified_split

log = logging.getLogger(__name__)

DATASET_COLUMNS = (
    "record_id",
    "region_id",
    "date",
    MONTH_COLUMN,
    *FEATURE_COLUMNS,
    TARGET_COLUMN,
    SPLIT_COLUMN,
)
LANDING_COLUMNS = ("source", "run_id", "chunk_key")
NORMAL_TOLERANCE_C = 0.005


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _zones(regions: list[Region], region_ids: pd.Series) -> np.ndarray:
    by_id = {r.id: r.zone for r in regions}
    return region_ids.map(by_id).to_numpy()


def rule_agreement(dataset: pd.DataFrame, criteria: RiskCriteria, regions: list[Region]) -> dict:
    """How often the rule applied to the *observed* features gives the stored label.

    Synthetic labels come from the true Tmax; the observed Tmax carries σ = 0.3 °C
    noise, so rows near a threshold can disagree. That is the dataset's irreducible
    error, and it is reported rather than hidden.
    """
    observed = classify(
        dataset["tmax_c"], dataset["normal_tmax_c"], _zones(regions, dataset["region_id"]), criteria
    )
    agree = observed == dataset[TARGET_COLUMN].to_numpy()
    disagreeing = dataset.loc[~agree]
    nearest_threshold = np.minimum.reduce(
        [
            (disagreeing["temp_deviation_c"] - criteria.departure_c[c]).abs()
            for c in ("HEATWAVE", "SEVERE_HEATWAVE")
        ]
        + [(disagreeing["tmax_c"] - min(criteria.min_tmax_c.values())).abs()]
    )
    return {
        "agreement": round(float(agree.mean()), 4),
        "disagreeing_rows": int((~agree).sum()),
        "max_distance_to_a_threshold_c_among_disagreeing": round(
            float(nearest_threshold.max()) if len(disagreeing) else 0.0, 2
        ),
    }


def prepare_modeling_dataset(
    raw: pd.DataFrame,
    normals: SeasonalNormals,
    criteria: RiskCriteria,
    regions: list[Region],
    *,
    test_fraction: float,
    validation_fraction: float,
    seed: int,
) -> tuple[pd.DataFrame, dict]:
    """Landed synthetic rows → the finished, split modelling dataset plus its audit record."""
    raw = raw.drop(columns=[c for c in LANDING_COLUMNS if c in raw.columns])

    # The landed normals must be the ones in the table now; otherwise the landed batch
    # predates a normals rebuild and its labels were drawn against different normals.
    landed_normal = raw["normal_tmax_c"].to_numpy()
    current_normal = normals.lookup(raw["region_id"], raw["date"])
    stale = int((np.abs(landed_normal - current_normal) > NORMAL_TOLERANCE_C).sum())
    if stale:
        raise ValueError(
            f"{stale} landed synthetic rows use different seasonal normals from "
            "config/seasonal_normals.csv. Re-land the batch: heatwave-prepare dataset --force"
        )

    cleaned, report = clean(raw)
    features = build_features(cleaned, normals)
    unknown = set(features[TARGET_COLUMN]) - set(criteria.classes)
    if unknown:
        raise ValueError(f"Unknown labels {sorted(unknown)}")

    features[SPLIT_COLUMN] = stratified_split(
        features[TARGET_COLUMN], test_fraction, validation_fraction, seed
    )
    dataset = features[list(DATASET_COLUMNS)].reset_index(drop=True)

    manifest = {
        "rows": len(dataset),
        "columns": list(DATASET_COLUMNS),
        "feature_columns": list(FEATURE_COLUMNS),
        "feature_labels": FEATURE_LABELS,
        "feature_units": FEATURE_UNITS,
        "non_feature_columns": {
            "record_id": "synthetic record number (traceability)",
            "region_id": "config/regions.yaml id (not a feature; field-availability §2.3)",
            "date": "calendar day (not a feature)",
            MONTH_COLUMN: "input to the seasonal imputer only (not a feature)",
            SPLIT_COLUMN: "train / validation / test",
        },
        "target": TARGET_COLUMN,
        "classes": list(criteria.classes),
        "class_to_index": criteria.class_to_index,
        "labeling_rule_version": criteria.version,
        "class_distribution": class_distribution(dataset, TARGET_COLUMN, criteria.classes),
        "split": {
            "method": "stratified on risk_class (sklearn train_test_split, twice)",
            "seed": seed,
            "fractions": {
                "train": round(1 - test_fraction - validation_fraction, 4),
                "validation": validation_fraction,
                "test": test_fraction,
            },
            "class_distribution": class_distribution(
                dataset, TARGET_COLUMN, criteria.classes, by=SPLIT_COLUMN
            ),
            "missing_values_left_for_imputer": {
                name: {
                    c: int(n)
                    for c, n in dataset.loc[dataset[SPLIT_COLUMN] == name, list(FEATURE_COLUMNS)]
                    .isna()
                    .sum()
                    .items()
                    if n
                }
                for name in SPLITS
            },
        },
        "cleaning": report.to_dict(),
        "label_vs_rule_on_observed_features": rule_agreement(dataset, criteria, regions),
    }
    return dataset, manifest


def build_observed_dataset(
    imd: pd.DataFrame,
    nasa: pd.DataFrame,
    normals: SeasonalNormals,
    criteria: RiskCriteria,
    regions: list[Region],
) -> tuple[pd.DataFrame, dict]:
    """Real history: IMD Tmax + NASA POWER for the other variables, labelled by the rule.

    Tmax and the normal both come from IMD (never NASA; field-availability §2.2). This
    is a reference set, not training data: real Mumbai history has almost no
    heatwave days (§2.6), so it serves Part 05 as a false-alarm check.
    """
    tmax = imd[["region_id", "date", "tmax_c"]]
    others = nasa[nasa["chunk_key"].str.contains("/year=", regex=False)]
    others = others[
        ["region_id", "date", "rh_pct", "wind_ms", "wind_height_m", "solar_mj_m2", "precip_mm"]
    ]
    merged = tmax.merge(others, on=["region_id", "date"], how="inner", validate="one_to_one")

    cleaned, report = clean(merged)
    features = build_features(cleaned, normals)
    features[TARGET_COLUMN] = classify(
        features["tmax_c"],
        features["normal_tmax_c"],
        _zones(regions, features["region_id"]),
        criteria,
    )
    columns = ["region_id", "date", MONTH_COLUMN, *FEATURE_COLUMNS, TARGET_COLUMN]
    dataset = features[columns].reset_index(drop=True)
    summary = {
        "rows": len(dataset),
        "date_range": [str(dataset["date"].min().date()), str(dataset["date"].max().date())],
        "sources": {"tmax_c": "imd", "normal_tmax_c": "imd 1991-2020", "others": "nasa_power"},
        "labeling_rule_version": criteria.version,
        "class_distribution": class_distribution(dataset, TARGET_COLUMN, criteria.classes),
        "tmax_c_max": float(dataset["tmax_c"].max()),
        "temp_deviation_c_max": float(dataset["temp_deviation_c"].max()),
        "cleaning": report.to_dict(),
    }
    return dataset, summary


def build_forecast_sample(forecast: pd.DataFrame, normals: SeasonalNormals) -> pd.DataFrame:
    """Latest forecast issue per region, through the live-inference feature path."""
    latest = forecast[
        forecast["issued_at"] == forecast.groupby("region_id")["issued_at"].transform("max")
    ]
    features = build_features(latest, normals)
    columns = ["region_id", "date", "lead_days", "issued_at", MONTH_COLUMN, *FEATURE_COLUMNS]
    return features[columns].sort_values(["region_id", "date"]).reset_index(drop=True)


def write_dataset(dataset: pd.DataFrame, manifest: dict, path: Path, manifest_path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dataset.assign(date=dataset["date"].dt.strftime("%Y-%m-%d"))
    out.to_csv(path, index=False, lineterminator="\n")
    manifest = {"path": path.name, "sha256": sha256_of(path), **manifest}
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest


def load_modeling_dataset(path: Path) -> dict[str, pd.DataFrame]:
    """Part 04's entry point: {"train": ..., "validation": ..., "test": ...}.

    Pass ``model_input(frame)`` as X (features + month) and ``frame["risk_class"]`` as y.
    """
    frame = pd.read_csv(path, parse_dates=["date"], dtype={"region_id": str})
    missing = set(DATASET_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns {sorted(missing)}")
    return {
        name: frame[frame[SPLIT_COLUMN] == name].drop(columns=SPLIT_COLUMN).reset_index(drop=True)
        for name in SPLITS
    }
