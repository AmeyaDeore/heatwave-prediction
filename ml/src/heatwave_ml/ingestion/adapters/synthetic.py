"""Synthetic dataset adapter.

Part 02 owns the landing format. Part 03 owns the generation logic, including
labelling rows with the IMD criteria in config/risk_classes.yaml. The adapter
takes any generator with the ``Generator`` signature, so Part 03 swaps in its
generator without touching ingestion.

``generate_placeholder`` exists only so the landing path runs end to end now. It
produces plausible, seasonally shaped, unlabelled rows, and it is **not** the
training dataset.
"""

from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd

from heatwave_ml.ingestion.adapters.base import Chunk, FetchResult
from heatwave_ml.ingestion.regions import Region

Generator = Callable[[list[Region], int, int, date, date], pd.DataFrame]

# Rough monthly mean Tmax (degC) for coastal Mumbai. It only gives the placeholder
# a seasonal shape. It is not an IMD normal and must not be used as one.
_PLACEHOLDER_MONTHLY_TMAX_C = np.array(
    [30.5, 31.0, 32.5, 33.0, 33.5, 32.0, 29.5, 29.0, 30.0, 32.5, 33.5, 32.0]
)
_MONSOON_MONTHS = [6, 7, 8, 9]


def generate_placeholder(
    regions: list[Region], count: int, seed: int, start: date, end: date
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    offsets = rng.integers(0, (end - start).days + 1, count)
    dates = pd.Timestamp(start) + pd.to_timedelta(offsets, unit="D")
    month = dates.month.to_numpy()
    monsoon = np.isin(month, _MONSOON_MONTHS)

    normal = _PLACEHOLDER_MONTHLY_TMAX_C[month - 1]
    deviation = rng.normal(0.0, 2.0, count)
    spikes = rng.random(count) < 0.08
    deviation[spikes] += rng.uniform(3.0, 9.0, spikes.sum())

    rains = rng.random(count) < np.where(monsoon, 0.8, 0.05)
    precip = np.where(monsoon, rng.gamma(0.8, 25.0, count), rng.gamma(0.5, 4.0, count)) * rains

    return pd.DataFrame(
        {
            "record_id": np.arange(count),
            "region_id": [regions[i].id for i in rng.integers(0, len(regions), count)],
            "date": dates,
            "tmax_c": normal + deviation,
            "normal_tmax_c": normal,
            "rh_pct": np.clip(
                np.where(monsoon, rng.normal(85, 6, count), rng.normal(65, 12, count)), 5, 100
            ),
            "wind_ms": rng.gamma(2.0, 1.2, count),
            "solar_mj_m2": np.clip(
                np.where(monsoon, rng.normal(13, 4, count), rng.normal(21, 3, count)), 0, None
            ),
            "precip_mm": precip,
        }
    ).round(
        {f: 2 for f in ("tmax_c", "normal_tmax_c", "rh_pct", "wind_ms", "solar_mj_m2", "precip_mm")}
    )


generate_placeholder.version = "placeholder-v0"


class SyntheticAdapter:
    name = "synthetic"
    # Synthetic rows are independent samples, so (region, date) may repeat.
    key_columns = ("record_id",)
    continuous_dates = False

    def __init__(
        self,
        regions: list[Region],
        count: int,
        seed: int,
        start: date,
        end: date,
        generator: Generator = generate_placeholder,
    ):
        self.regions = regions
        self.count = count
        self.seed = seed
        self.start = start
        self.end = end
        self.generator = generator

    @property
    def generator_version(self) -> str:
        return getattr(self.generator, "version", self.generator.__name__)

    def chunks(self) -> list[Chunk]:
        """One deterministic batch: same generator, seed and count always give the same rows."""
        return [
            Chunk(
                key=f"generator={self.generator_version}/seed={self.seed}-n={self.count}",
                start=self.start,
                end=self.end,
            )
        ]

    def fetch(self, chunk: Chunk) -> FetchResult:
        frame = self.generator(self.regions, self.count, self.seed, chunk.start, chunk.end)
        return FetchResult(
            frame=frame,
            notes={"generator": self.generator_version, "seed": self.seed, "count": self.count},
        )
