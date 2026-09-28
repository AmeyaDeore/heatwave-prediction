"""Monitored regions, read from config/regions.yaml (never hard-coded)."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    district: str
    state: str
    zone: str
    lat: float
    lon: float


def load_regions(path: Path, only: list[str] | None = None) -> list[Region]:
    """Load every region in ``path``, or just the ids in ``only`` (unknown ids are an error)."""
    with path.open(encoding="utf-8") as fh:
        regions = [Region(**entry) for entry in yaml.safe_load(fh)["regions"]]

    if only is None:
        return regions
    by_id = {region.id: region for region in regions}
    unknown = sorted(set(only) - by_id.keys())
    if unknown:
        raise ValueError(f"Unknown region id(s) {unknown}; known: {sorted(by_id)}")
    return [by_id[region_id] for region_id in only]
