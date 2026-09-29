"""Row-level cleaning, applied before the split and to every data source.

Stateless on purpose: nothing here learns a statistic from the data, so running it
over the whole dataset before splitting cannot leak test information. Imputation
and scaling, which do learn statistics, live in ``features/preprocessor.py`` and are
fit on training rows only.

Every action is counted in a ``CleaningReport`` and logged, so data quality can be
audited ("N rows had humidity above 100 %, capped to 100").
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from heatwave_ml.ingestion.quality import PLAUSIBLE_BOUNDS

log = logging.getLogger(__name__)

MEASURED_COLUMNS = ("tmax_c", "rh_pct", "wind_ms", "solar_mj_m2", "precip_mm")

# How far outside PLAUSIBLE_BOUNDS a value may be and still be capped to the bound
# (instrument saturation or rounding) instead of being treated as invalid (set to
# missing, then dropped or imputed). Rationale per feature: docs/data/preprocessing.md.
CAP_TOLERANCE = {
    "tmax_c": 0.0,  # never capped: the label depends on it, so a wrong Tmax is dropped
    "rh_pct": 5.0,  # 100-105 % is sensor saturation in fog/rain: cap to 100
    "wind_ms": 0.5,  # -0.5-0 is a calibration offset near calm: cap to 0
    "solar_mj_m2": 0.5,  # same, near night-time/overcast zero
    "precip_mm": 0.5,  # same, near zero rain
}


@dataclass
class CleaningReport:
    rows_in: int = 0
    rows_out: int = 0
    actions: list[dict] = field(default_factory=list)

    def record(self, step: str, column: str | None, action: str, rows: int) -> None:
        if rows:
            self.actions.append({"step": step, "column": column, "action": action, "rows": rows})
            log.info("%s: %s rows %s%s", step, rows, action, f" ({column})" if column else "")

    def count(self, step: str, column: str | None = None) -> int:
        return sum(
            a["rows"]
            for a in self.actions
            if a["step"] == step and (column is None or a["column"] == column)
        )

    def to_dict(self) -> dict:
        return {"rows_in": self.rows_in, "rows_out": self.rows_out, "actions": self.actions}


def clean(frame: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """Types → invalid values → duplicates → rows without Tmax. Returns (clean frame, report).

    Missing values in rh/wind/solar/precip are counted but kept: the fitted imputer
    fills them. Units are normalised afterwards by ``build_features``.
    """
    report = CleaningReport(rows_in=len(frame))
    out = frame.copy()

    # 1. Types. Anything unparseable becomes missing and is handled below. Values are
    # rounded to 0.01 so float32 sources (IMD) don't carry 39.52000045776367-style noise.
    for column in MEASURED_COLUMNS:
        before = out[column].isna()
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("float64").round(2)
        report.record(
            "types", column, "unparseable → missing", int((out[column].isna() & ~before).sum())
        )
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    no_key = out["region_id"].isna() | out["date"].isna()
    report.record("types", None, "dropped: no region or date", int(no_key.sum()))
    out = out[~no_key]

    # 2. Physically invalid values: cap if just outside the bound, else mark missing.
    for column in MEASURED_COLUMNS:
        low, high = PLAUSIBLE_BOUNDS[column]
        tolerance = CAP_TOLERANCE[column]
        values = out[column]
        cap_low = values.between(low - tolerance, low, inclusive="left")
        cap_high = values.between(high, high + tolerance, inclusive="right")
        invalid = ((values < low - tolerance) | (values > high + tolerance)) & values.notna()
        out.loc[cap_low, column] = low
        out.loc[cap_high, column] = high
        out.loc[invalid, column] = np.nan
        report.record("invalid", column, f"capped to {low}", int(cap_low.sum()))
        report.record("invalid", column, f"capped to {high}", int(cap_high.sum()))
        report.record("invalid", column, "out of bounds → missing", int(invalid.sum()))

    # 3. Duplicates on location + date. Keep the first; say whether the copies disagreed.
    key = ["region_id", "date"]
    duplicated = out.duplicated(key, keep="first")
    if duplicated.any():
        dup_groups = out[out.duplicated(key, keep=False)]
        conflicting = dup_groups.groupby(key)[list(MEASURED_COLUMNS)].nunique(dropna=False)
        n_conflicting = int((conflicting > 1).any(axis=1).sum())
        report.record("duplicates", None, "dropped: repeat region+date", int(duplicated.sum()))
        report.record("duplicates", None, "of which the repeats disagreed", n_conflicting)
    out = out[~duplicated]

    # 4. No Tmax → no label and no deviation. Imputing it would invent the target signal.
    no_tmax = out["tmax_c"].isna()
    report.record("missing", "tmax_c", "dropped: Tmax missing", int(no_tmax.sum()))
    out = out[~no_tmax]

    # 5. Remaining gaps are left for the fitted imputer; count them for the audit trail.
    for column in MEASURED_COLUMNS[1:]:
        report.record(
            "missing", column, "left missing for the fitted imputer", int(out[column].isna().sum())
        )

    out = out.sort_values(key, kind="stable").reset_index(drop=True)
    report.rows_out = len(out)
    return out, report
