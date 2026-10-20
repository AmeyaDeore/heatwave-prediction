"""Monitored regions, read from config/regions.yaml (never hard-coded).

Revision 2 (Part 02 R2.2) adds three optional fields for the Maharashtra map and analysis:
``division`` (one of Maharashtra's administrative divisions), ``kind`` (``city`` or ``area``)
and ``parent`` (the city an area belongs to, e.g. kurla → mumbai). Older entries without
them still load. Any other unknown key is still an error, so a typo cannot be ignored.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

REGION_KINDS = ("city", "area")


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    district: str
    state: str
    zone: str
    lat: float
    lon: float
    division: str | None = None
    kind: str = "city"
    parent: str | None = None


def validate_hierarchy(regions: list[Region]) -> None:
    """Every ``kind`` is known, and every area names an existing city as its parent."""
    by_id = {region.id: region for region in regions}
    for region in regions:
        if region.kind not in REGION_KINDS:
            raise ValueError(
                f"Region '{region.id}': kind '{region.kind}' is not one of {REGION_KINDS}"
            )
        if region.kind == "area":
            parent = by_id.get(region.parent) if region.parent else None
            if parent is None or parent.kind != "city":
                raise ValueError(
                    f"Region '{region.id}' is an area, so 'parent' must name a city in the "
                    f"same file (got {region.parent!r})"
                )
        elif region.parent is not None:
            raise ValueError(f"Region '{region.id}' is a city and cannot have a parent")


def load_regions(path: Path, only: list[str] | None = None) -> list[Region]:
    """Load every region in ``path``, or just the ids in ``only`` (unknown ids are an error)."""
    with path.open(encoding="utf-8") as fh:
        regions = [Region(**entry) for entry in yaml.safe_load(fh)["regions"]]
    validate_hierarchy(regions)

    if only is None:
        return regions
    by_id = {region.id: region for region in regions}
    unknown = sorted(set(only) - by_id.keys())
    if unknown:
        raise ValueError(f"Unknown region id(s) {unknown}; known: {sorted(by_id)}")
    return [by_id[region_id] for region_id in only]
