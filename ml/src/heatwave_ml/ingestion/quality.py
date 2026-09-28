"""Ingestion-time data quality checks.

These checks only flag and count problems. They never drop or fix rows. The
report goes into the ingestion log so Part 03 can handle each problem on purpose.
"""

import pandas as pd

# Loose physical bounds. A value outside them is almost certainly an error, not weather.
PLAUSIBLE_BOUNDS = {
    "tmax_c": (-10.0, 55.0),
    "normal_tmax_c": (-10.0, 55.0),
    "rh_pct": (0.0, 100.0),
    "wind_ms": (0.0, 60.0),
    "solar_mj_m2": (0.0, 45.0),
    "precip_mm": (0.0, 1000.0),
}


def check_frame(frame: pd.DataFrame, key_columns: tuple[str, ...], continuous_dates: bool) -> dict:
    fields = [f for f in PLAUSIBLE_BOUNDS if f in frame.columns]
    report: dict = {"rows": len(frame)}

    nulls = {f: int(n) for f in fields if (n := frame[f].isna().sum())}
    invalid = {}
    for f in fields:
        low, high = PLAUSIBLE_BOUNDS[f]
        values = frame[f].dropna()
        if n := int(((values < low) | (values > high)).sum()):
            invalid[f] = n
    duplicates = int(frame.duplicated(list(key_columns)).sum())

    gaps = {}
    if continuous_dates and not frame.empty:
        for region_id, group in frame.groupby("region_id"):
            expected = pd.date_range(group["date"].min(), group["date"].max(), freq="D")
            missing = expected.difference(pd.DatetimeIndex(group["date"]))
            if len(missing):
                gaps[region_id] = {
                    "missing_days": len(missing),
                    "first_missing": [d.date().isoformat() for d in missing[:5]],
                }

    if nulls:
        report["nulls"] = nulls
    if invalid:
        report["invalid"] = invalid
    if duplicates:
        report["duplicate_keys"] = duplicates
    if gaps:
        report["date_gaps"] = gaps
    report["has_issues"] = bool(nulls or invalid or duplicates or gaps)
    return report
