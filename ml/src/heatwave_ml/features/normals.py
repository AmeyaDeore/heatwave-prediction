"""Seasonal normal maximum temperature per region and day of year.

Neither IMD nor NASA POWER publishes a daily normal (field-availability.md §2.1), so
it is derived once from IMD gridded Tmax and committed as a table:

- period 1991-2020 (the WMO standard 30-year normal period),
- mean Tmax per region and day of year, on a 366-day calendar (Feb 29 is day 60
  and non-leap years skip it), then
- a centred, circular 31-day moving average (±15 days), so the normal is smooth
  across months and across the Dec→Jan wrap.

Training, the synthetic generator and live inference all read the same table,
so the normal (and therefore Temperature Deviation) is identical everywhere.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DAYS_IN_CALENDAR = 366
DEFAULT_PERIOD = (1991, 2020)
DEFAULT_HALF_WINDOW_DAYS = 15


def calendar_day(dates) -> np.ndarray:
    """Day of year on a 366-day calendar, so a date's day number is the same every year."""
    dates = pd.DatetimeIndex(pd.to_datetime(dates))
    shift = (~dates.is_leap_year) & (dates.month > 2)
    return (dates.dayofyear + shift.astype(int)).to_numpy()


def _circular_smooth(values: np.ndarray, half_window: int) -> np.ndarray:
    padded = np.concatenate([values[-half_window:], values, values[:half_window]])
    kernel = np.ones(2 * half_window + 1) / (2 * half_window + 1)
    return np.convolve(padded, kernel, mode="valid")


@dataclass(frozen=True)
class SeasonalNormals:
    """Table with columns region_id, day_of_year (1-366), normal_tmax_c."""

    table: pd.DataFrame

    @classmethod
    def from_imd(
        cls,
        imd: pd.DataFrame,
        period: tuple[int, int] = DEFAULT_PERIOD,
        half_window: int = DEFAULT_HALF_WINDOW_DAYS,
        min_years: int = 25,
    ) -> "SeasonalNormals":
        """Derive the table from landed IMD rows (region_id, date, tmax_c)."""
        years = imd["date"].dt.year
        base = imd[(years >= period[0]) & (years <= period[1])].dropna(subset=["tmax_c"])
        coverage = base.groupby("region_id")["date"].apply(lambda d: d.dt.year.nunique())
        short = coverage[coverage < min_years]
        if not short.empty:
            raise ValueError(
                f"Normals need >= {min_years} years in {period}; too few for {short.to_dict()}. "
                "Land the missing IMD years first (heatwave-ingest historical --source imd)."
            )

        base = base.assign(day_of_year=calendar_day(base["date"]))
        daily = base.groupby(["region_id", "day_of_year"])["tmax_c"].mean()
        rows = []
        for region_id, series in daily.groupby(level="region_id"):
            raw = series.droplevel("region_id").reindex(range(1, DAYS_IN_CALENDAR + 1))
            # Feb 29 only exists in ~7 of the 30 years; fill any gap from its neighbours.
            raw = raw.interpolate(limit_direction="both")
            smoothed = _circular_smooth(raw.to_numpy(), half_window)
            rows.append(
                pd.DataFrame(
                    {
                        "region_id": region_id,
                        "day_of_year": np.arange(1, DAYS_IN_CALENDAR + 1),
                        "normal_tmax_c": np.round(smoothed, 2),
                    }
                )
            )
        return cls(pd.concat(rows, ignore_index=True))

    @classmethod
    def load(cls, path: Path) -> "SeasonalNormals":
        if not path.exists():
            raise FileNotFoundError(
                f"No seasonal normals at {path}. Build them with: uv run heatwave-prepare normals"
            )
        return cls(pd.read_csv(path, dtype={"region_id": str}))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.table.to_csv(path, index=False, lineterminator="\n")

    @property
    def regions(self) -> set[str]:
        return set(self.table["region_id"])

    def lookup(self, region_ids, dates) -> np.ndarray:
        """Normal Tmax for each (region, date) pair. Unknown regions raise."""
        region_ids = np.asarray(region_ids, dtype=object)
        unknown = set(region_ids) - self.regions
        if unknown:
            raise KeyError(
                f"No seasonal normals for region(s) {sorted(unknown)}. "
                "Rebuild them after adding a region: uv run heatwave-prepare normals"
            )
        index = pd.MultiIndex.from_arrays([region_ids, calendar_day(dates)])
        values = self.table.set_index(["region_id", "day_of_year"])["normal_tmax_c"]
        return values.reindex(index).to_numpy()
