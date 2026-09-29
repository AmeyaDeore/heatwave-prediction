"""Part 03 training-side steps: cleaning, synthetic generation, split, dataset build."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from conftest import TEST_REGIONS

from heatwave_ml.features import classify, model_input
from heatwave_ml.ingestion.adapters.synthetic import SyntheticAdapter
from heatwave_ml.preprocessing.cleaning import clean
from heatwave_ml.preprocessing.dataset import (
    DATASET_COLUMNS,
    load_modeling_dataset,
    prepare_modeling_dataset,
    write_dataset,
)
from heatwave_ml.preprocessing.split import stratified_split
from heatwave_ml.preprocessing.synthetic import SyntheticGeneratorV1

START, END = date(2000, 1, 1), date(2024, 12, 31)


@pytest.fixture(scope="module")
def normals(fake_normals):
    # Normals run up to ~36 °C, warm enough for every class, like the Andheri IMD cell.
    return fake_normals


@pytest.fixture(scope="module")
def generator(normals, criteria):
    return SyntheticGeneratorV1(normals, criteria)


@pytest.fixture(scope="module")
def raw(generator):
    return generator(TEST_REGIONS, 3000, 7, START, END)


# --- Cleaning -------------------------------------------------------------------------------


def dirty_frame() -> pd.DataFrame:
    rows = [
        # region, date, tmax, rh, wind, solar, precip
        ("mumbai", "2024-04-01", 36.0, 102.0, 2.0, 24.0, 0.0),  # rh just over 100: cap
        ("mumbai", "2024-04-02", 36.0, 999.0, -0.3, 24.0, 0.0),  # rh garbage: missing; wind cap 0
        ("mumbai", "2024-04-03", 99.9, 50.0, 2.0, -999.0, 0.0),  # tmax sentinel: dropped
        ("mumbai", "2024-04-04", None, 50.0, 2.0, 24.0, 0.0),  # no tmax: dropped
        ("mumbai", "2024-04-05", 35.0, 50.0, 2.0, 24.0, "n/a"),  # unparseable precip: missing
        ("mumbai", "2024-04-06", 35.0, 50.0, 2.0, 24.0, 0.0),
        ("mumbai", "2024-04-06", 35.0, 50.0, 2.0, 24.0, 0.0),  # exact duplicate
        ("mumbai", "2024-04-07", 35.0, 50.0, 2.0, 24.0, 0.0),
        ("mumbai", "2024-04-07", 35.0, 55.0, 2.0, 24.0, 0.0),  # conflicting duplicate
        ("andheri", "2024-04-07", 35.0, 50.0, 2.0, 24.0, 0.0),  # same date, other region: kept
    ]
    columns = ["region_id", "date", "tmax_c", "rh_pct", "wind_ms", "solar_mj_m2", "precip_mm"]
    return pd.DataFrame(rows, columns=columns)


def test_cleaning_caps_drops_and_counts_each_decision():
    out, report = clean(dirty_frame())
    assert report.rows_in == 10 and report.rows_out == len(out) == 6
    assert report.count("invalid", "rh_pct") == 2  # one capped, one set missing
    assert report.count("invalid", "tmax_c") == 1
    assert report.count("invalid", "solar_mj_m2") == 1
    assert report.count("invalid", "wind_ms") == 1
    assert report.count("types", "precip_mm") == 1
    assert report.count("missing", "tmax_c") == 2  # the sentinel row and the empty one
    dup = {a["action"]: a["rows"] for a in report.actions if a["step"] == "duplicates"}
    assert dup == {"dropped: repeat region+date": 2, "of which the repeats disagreed": 1}

    by_date = out[out.region_id == "mumbai"].set_index("date")
    assert by_date.loc["2024-04-01", "rh_pct"] == 100.0
    assert np.isnan(by_date.loc["2024-04-02", "rh_pct"])
    assert by_date.loc["2024-04-02", "wind_ms"] == 0.0
    assert by_date.loc["2024-04-07", "rh_pct"] == 50.0  # first copy kept
    assert not out.duplicated(["region_id", "date"]).any()
    assert out["tmax_c"].notna().all()


# --- Synthetic generator --------------------------------------------------------------------


def test_generator_is_deterministic_for_a_seed(generator, regions, raw):
    again = generator(regions, 3000, 7, START, END)
    pd.testing.assert_frame_equal(raw, again)
    other = generator(regions, 3000, 8, START, END)
    assert not raw["tmax_c"].equals(other["tmax_c"])


def test_generator_output_fits_the_landing_contract(generator, regions, raw):
    assert len(raw) == 3000 and raw["record_id"].is_unique
    assert set(raw["region_id"]) == {r.id for r in regions}
    assert raw["date"].between(pd.Timestamp(START), pd.Timestamp(END)).all()
    assert (raw["wind_height_m"] == 2).all()
    adapter = SyntheticAdapter(regions, 3000, 7, START, END, generator=generator)
    assert adapter.chunks()[0].key == "generator=imd-sim-v1/seed=7-n=3000"


def test_generator_injects_realistic_defects(raw):
    assert (
        raw[["rh_pct", "wind_ms", "solar_mj_m2", "precip_mm"]].isna().sum().between(20, 110).all()
    )
    assert raw["tmax_c"].isna().sum() >= 1
    assert raw.duplicated(["region_id", "date"]).sum() == 12  # 0.4 % re-landed records
    assert (raw["rh_pct"] > 100).any() and (raw[["solar_mj_m2", "precip_mm"]] < 0).any().any()


def test_generator_labels_follow_the_rule_away_from_thresholds(raw, criteria):
    """Labels come from the true Tmax; only noise near a threshold may flip them."""
    rows = raw.dropna(subset=["tmax_c"])
    rows = rows[rows["tmax_c"] < 55]
    deviation = rows["tmax_c"] - rows["normal_tmax_c"]
    far = (
        ((deviation - 4.5).abs() > 1.5)
        & ((deviation - 6.5).abs() > 1.5)
        & ((rows["tmax_c"] - 37).abs() > 1.5)
    )
    observed = classify(rows["tmax_c"], rows["normal_tmax_c"], "coastal", criteria)
    assert far.sum() > 1500
    assert (observed[far.to_numpy()] == rows.loc[far, "risk_class"].to_numpy()).all()


def test_generator_has_every_class_with_normal_the_majority(raw):
    share = raw["risk_class"].value_counts(normalize=True)
    assert set(share.index) == {"NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"}
    assert share["NORMAL"] > 0.6
    assert share["HEATWAVE"] > 0.04 and share["SEVERE_HEATWAVE"] > 0.04


def test_generator_places_borderline_cases(raw):
    deviation = raw["tmax_c"] - raw["normal_tmax_c"]
    near = ((deviation - 4.5).abs() <= 0.5) | ((deviation - 6.5).abs() <= 0.5)
    assert near.mean() > 0.08


def test_generator_weather_is_physically_consistent(raw):
    valid = raw[(raw["rh_pct"] <= 100) & (raw["solar_mj_m2"] >= 0) & (raw["precip_mm"] >= 0)]
    hot = valid[valid["risk_class"] != "NORMAL"]
    normal = valid[valid["risk_class"] == "NORMAL"]
    assert hot["rh_pct"].median() < normal["rh_pct"].median()  # dry heat
    assert hot["precip_mm"].mean() < normal["precip_mm"].mean()
    assert raw["tmax_c"].dropna().loc[lambda s: s < 55].max() <= 45.5  # ceiling + noise


# --- Split ----------------------------------------------------------------------------------


def test_split_is_stratified_disjoint_and_seeded():
    labels = pd.Series(["NORMAL"] * 800 + ["HEATWAVE"] * 120 + ["SEVERE_HEATWAVE"] * 80)
    split = stratified_split(labels, 0.15, 0.15, seed=42)
    assert split.value_counts().to_dict() == {"train": 700, "validation": 150, "test": 150}
    for name in ("train", "validation", "test"):
        share = labels[split == name].value_counts(normalize=True)
        assert abs(share["SEVERE_HEATWAVE"] - 0.08) < 0.01
        assert abs(share["HEATWAVE"] - 0.12) < 0.01
    assert split.equals(stratified_split(labels, 0.15, 0.15, seed=42))
    assert not split.equals(stratified_split(labels, 0.15, 0.15, seed=1))


# --- End to end -----------------------------------------------------------------------------


def test_dataset_build_end_to_end(raw, normals, criteria, regions, tmp_path):
    dataset, manifest = prepare_modeling_dataset(
        raw, normals, criteria, regions, test_fraction=0.15, validation_fraction=0.15, seed=42
    )
    assert list(dataset.columns) == list(DATASET_COLUMNS)
    assert not dataset.duplicated(["region_id", "date"]).any()
    assert dataset["tmax_c"].notna().all() and dataset["temp_deviation_c"].notna().all()
    assert (
        dataset["temp_deviation_c"] == (dataset["tmax_c"] - dataset["normal_tmax_c"]).round(2)
    ).all()
    assert manifest["rows"] == len(dataset) == manifest["cleaning"]["rows_out"]
    assert manifest["labeling_rule_version"] == criteria.version
    per_split = manifest["split"]["class_distribution"]
    assert sum(s["rows"] for s in per_split.values()) == len(dataset)
    assert 0.9 < manifest["label_vs_rule_on_observed_features"]["agreement"] < 1.0

    path = tmp_path / "heatwave_dataset.csv"
    written = write_dataset(dataset, manifest, path, tmp_path / "heatwave_dataset.manifest.json")
    splits = load_modeling_dataset(path)
    assert {k: len(v) for k, v in splits.items()} == {k: v["rows"] for k, v in per_split.items()}
    assert len(written["sha256"]) == 64
    ids = [set(frame["record_id"]) for frame in splits.values()]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
    assert list(model_input(splits["train"]).columns)[-1] == "month"


def test_dataset_build_rejects_a_batch_landed_with_other_normals(raw, normals, criteria, regions):
    stale = raw.assign(normal_tmax_c=raw["normal_tmax_c"] + 0.5)
    with pytest.raises(ValueError, match="--force"):
        prepare_modeling_dataset(
            stale, normals, criteria, regions, test_fraction=0.15, validation_fraction=0.15, seed=42
        )
