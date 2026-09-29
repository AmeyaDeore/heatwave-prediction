"""Shared feature logic: labelling rule, Temperature Deviation, normals, parity, preprocessor."""

import math

import numpy as np
import pandas as pd
import pytest

from heatwave_ml.features import (
    FEATURE_COLUMNS,
    SeasonalNormals,
    build_features,
    classify,
    model_input,
    preprocessor_for,
    temperature_deviation,
    wind_at_height,
)
from heatwave_ml.features.normals import calendar_day
from heatwave_ml.ingestion.regions import load_regions
from heatwave_ml.ingestion.settings import REPO_ROOT


@pytest.fixture
def normals(fake_normals):
    return fake_normals


# --- Temperature Deviation: hand-checked examples ------------------------------------------


@pytest.mark.parametrize(
    ("tmax", "normal", "expected"),
    [
        (41.5, 37.0, 4.5),
        (36.2, 29.9, 6.3),
        (30.0, 32.25, -2.25),
        (41.1, 36.6, 4.5),  # 41.1 - 36.6 = 4.500000000000004 in floating point
        (39.52000045776367, 34.73, 4.79),  # float32 IMD value
    ],
)
def test_temperature_deviation_hand_checked(tmax, normal, expected):
    assert temperature_deviation(tmax, normal) == expected


# --- Labelling rule: hand-checked examples --------------------------------------------------


@pytest.mark.parametrize(
    ("tmax", "normal", "zone", "expected", "why"),
    [
        (37.0, 32.5, "coastal", "HEATWAVE", "both boundaries inclusive: Tmax 37, departure 4.5"),
        (37.0, 30.5, "coastal", "SEVERE_HEATWAVE", "departure exactly 6.5"),
        (36.9, 30.0, "coastal", "NORMAL", "departure 6.9 but Tmax below the coastal minimum"),
        (38.0, 33.6, "coastal", "NORMAL", "departure 4.4"),
        (41.1, 36.6, "coastal", "HEATWAVE", "float rounding must not push 4.5 below the line"),
        (40.0, 35.5, "plains", "HEATWAVE", "plains minimum is 40"),
        (39.9, 33.0, "plains", "NORMAL", "departure 6.9 but below the plains minimum"),
        (30.0, 25.5, "hills", "HEATWAVE", "hills minimum is 30"),
        (45.0, 43.0, "plains", "HEATWAVE", "absolute 45 even with departure 2"),
        (47.0, 45.0, "plains", "SEVERE_HEATWAVE", "absolute 47"),
        (45.5, 38.5, "plains", "SEVERE_HEATWAVE", "absolute says HW, departure 7 says severe"),
        (32.0, 32.0, "coastal", "NORMAL", "an ordinary day"),
    ],
)
def test_rule_hand_checked(criteria, tmax, normal, zone, expected, why):
    assert classify([tmax], [normal], [zone], criteria)[0] == expected, why


def test_rule_refuses_missing_values_and_unknown_zones(criteria):
    with pytest.raises(ValueError, match="clean the data"):
        classify([np.nan], [30.0], ["coastal"], criteria)
    with pytest.raises(ValueError, match="zone"):
        classify([40.0], [30.0], ["desert"], criteria)


def test_criteria_come_from_config_with_fixed_class_order(criteria):
    assert criteria.classes == ("NORMAL", "HEATWAVE", "SEVERE_HEATWAVE")
    assert criteria.class_to_index == {"NORMAL": 0, "HEATWAVE": 1, "SEVERE_HEATWAVE": 2}
    assert criteria.version.startswith("IMD-HW-")
    assert criteria.min_tmax_c["coastal"] == 37.0


# --- Seasonal normals -----------------------------------------------------------------------


def test_calendar_day_is_stable_across_leap_years():
    days = calendar_day(["2023-02-28", "2023-03-01", "2024-02-29", "2024-03-01", "2023-12-31"])
    assert days.tolist() == [59, 61, 60, 61, 366]


def test_normals_cover_every_day_are_smooth_and_wrap(normals):
    table = normals.table
    assert len(table) == 2 * 366 and not table["normal_tmax_c"].isna().any()
    mumbai = table[table.region_id == "mumbai"]["normal_tmax_c"].to_numpy()
    assert np.abs(np.diff(mumbai)).max() < 0.3  # smooth day to day
    assert abs(mumbai[0] - mumbai[-1]) < 0.3  # no jump at Dec 31 → Jan 1
    assert mumbai.max() - mumbai.min() > 4  # the seasonal cycle survives smoothing


def test_normals_need_enough_years(fake_imd):
    with pytest.raises(ValueError, match="years"):
        SeasonalNormals.from_imd(fake_imd(years=range(2015, 2021)))


def test_normals_lookup_roundtrip_and_unknown_region(normals, tmp_path):
    path = tmp_path / "normals.csv"
    normals.save(path)
    loaded = SeasonalNormals.load(path)
    dates = ["2020-02-29", "2023-07-15"]
    assert np.allclose(
        loaded.lookup(["mumbai", "andheri"], dates), normals.lookup(["mumbai", "andheri"], dates)
    )
    with pytest.raises(KeyError, match="colaba"):
        normals.lookup(["colaba"], ["2023-07-15"])


def test_committed_normals_cover_every_configured_region():
    committed = SeasonalNormals.load(REPO_ROOT / "config" / "seasonal_normals.csv")
    configured = {r.id for r in load_regions(REPO_ROOT / "config" / "regions.yaml")}
    assert configured <= committed.regions
    assert len(committed.table) == 366 * len(committed.regions)


# --- Train/inference parity -----------------------------------------------------------------


def test_wind_height_conversion_matches_fao56():
    assert math.isclose(float(wind_at_height(1.0, 10)), 0.748, abs_tol=5e-4)
    assert float(wind_at_height(3.0, 2)) == 3.0


def weather_row(**overrides) -> dict:
    row = {
        "region_id": "mumbai",
        "date": "2024-04-20",
        "tmax_c": 39.0,
        "rh_pct": 40.0,
        "wind_ms": 2.0,
        "wind_height_m": 2,
        "solar_mj_m2": 25.0,
        "precip_mm": 0.0,
    }
    return row | overrides


def test_same_weather_gives_same_features_on_training_and_inference_paths(normals):
    """A training row (2 m wind, with a normal already attached) and a forecast row (10 m
    wind, no normal) describing the same weather must produce identical features."""
    training = pd.DataFrame([weather_row(normal_tmax_c=12.3)])  # a wrong normal gets replaced
    forecast = pd.DataFrame([weather_row(wind_ms=2.0 / 0.7480, wind_height_m=10, lead_days=2)])
    a = build_features(training, normals)[list(FEATURE_COLUMNS)]
    b = build_features(forecast, normals)[list(FEATURE_COLUMNS)]
    pd.testing.assert_frame_equal(a, b, atol=0.01)

    expected_normal = normals.lookup(["mumbai"], ["2024-04-20"])[0]
    assert a.loc[0, "normal_tmax_c"] == expected_normal
    assert a.loc[0, "temp_deviation_c"] == round(39.0 - expected_normal, 2)


def test_build_features_refuses_ambiguous_or_wrong_units(normals):
    with pytest.raises(KeyError, match="wind_height_m"):
        build_features(pd.DataFrame([weather_row()]).drop(columns="wind_height_m"), normals)
    with pytest.raises(ValueError, match="Kelvin"):
        build_features(pd.DataFrame([weather_row(tmax_c=312.15)]), normals)


# --- Fitted preprocessing: no leakage, scaling only for linear models -----------------------


def feature_frame(n: int, seed: int, month: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({c: rng.normal(30, 5, n) for c in FEATURE_COLUMNS})
    frame["month"] = month
    return frame


def test_imputer_learns_from_training_rows_only():
    train = feature_frame(50, 1, month=4)
    train.loc[:9, "rh_pct"] = np.nan
    test = feature_frame(20, 2, month=4)
    test["rh_pct"] = np.nan
    test.loc[:4, "rh_pct"] = 1000.0  # extreme test values must not move the fitted median

    pre = preprocessor_for("random_forest").fit(model_input(train))
    out = pre.transform(model_input(test))
    train_median = train["rh_pct"].median()
    assert (out["rh_pct"].iloc[5:] == train_median).all()
    assert pre.named_steps["impute"].monthly_medians_["rh_pct"][4] == train_median


def test_imputer_uses_the_rows_month_and_falls_back_to_overall():
    train = pd.concat([feature_frame(10, 1, month=1), feature_frame(10, 2, month=7)])
    train.loc[train.month == 1, "precip_mm"] = 0.0
    train.loc[train.month == 7, "precip_mm"] = 20.0
    live = feature_frame(3, 3, month=1)
    live["month"] = [1, 7, 3]  # March never seen in training
    live["precip_mm"] = np.nan
    out = preprocessor_for("xgboost").fit(model_input(train)).transform(model_input(live))
    assert out["precip_mm"].tolist() == [0.0, 20.0, 10.0]


def test_imputer_never_fills_tmax():
    train = feature_frame(10, 1, month=4)
    live = feature_frame(1, 2, month=4)
    live["tmax_c"] = np.nan
    pre = preprocessor_for("xgboost").fit(model_input(train))
    with pytest.raises(ValueError, match="tmax_c"):
        pre.transform(model_input(live))


def test_scaling_only_for_logistic_regression_and_fit_on_train():
    train, test = feature_frame(100, 1, month=5), feature_frame(100, 2, month=5) + 50
    linear = preprocessor_for("logistic_regression").fit(model_input(train))
    scaled = linear.transform(model_input(train))
    assert np.allclose(scaled.mean(), 0, atol=1e-9)
    assert np.allclose(linear.named_steps["scale"].mean_, train[list(FEATURE_COLUMNS)].mean())
    assert linear.transform(model_input(test)).mean().min() > 5  # test not re-centred

    for tree in ("random_forest", "xgboost"):
        pre = preprocessor_for(tree)
        assert pre.named_steps["scale"] == "passthrough"
        out = pre.fit(model_input(train)).transform(model_input(train))
        assert list(out.columns) == list(FEATURE_COLUMNS)
        pd.testing.assert_frame_equal(out, train[list(FEATURE_COLUMNS)])
