"""The raw landing zone: immutable, append-only, partitioned by source and chunk.

    <RAW_DATA_DIR>/<source>/<chunk key>/<run_id>.parquet       tabular, canonical columns
    <RAW_DATA_DIR>/<source>/<chunk key>/<run_id>.native.<ext>  the source's bytes, untouched

e.g. ``data/raw/nasa_power/region=mumbai/year=2023/20260928T101500.123456Z-3f9a1c.parquet``.

Nothing is ever overwritten. A re-fetch lands a new ``run_id`` next to the old
one, and readers take the newest version per chunk. Part 03 should read through
``read_latest`` rather than walking the tree itself.
"""

from pathlib import Path

import pandas as pd

from heatwave_ml.ingestion.adapters.base import FetchResult


class RawLandingZone:
    def __init__(self, root: Path):
        self.root = root

    def chunk_dir(self, source: str, key: str) -> Path:
        return self.root / source / key

    def has(self, source: str, key: str) -> bool:
        return any(self.chunk_dir(source, key).glob("*.parquet"))

    def write(self, source: str, key: str, run_id: str, result: FetchResult) -> dict[str, str]:
        directory = self.chunk_dir(source, key)
        directory.mkdir(parents=True, exist_ok=True)
        written = {}

        if result.native is not None:
            native_path = directory / f"{run_id}.native.{result.native.extension}"
            with native_path.open("xb") as fh:  # "x": fail rather than overwrite
                fh.write(result.native.content)
            written["native"] = native_path.relative_to(self.root).as_posix()

        final_path = directory / f"{run_id}.parquet"
        if final_path.exists():
            raise FileExistsError(f"Refusing to overwrite raw file {final_path}")
        # Write under a temporary name, then rename, so a crash never leaves a
        # half-written parquet that resume would mistake for a landed chunk.
        temp_path = directory / f".{run_id}.parquet.tmp"
        result.frame.assign(source=source, run_id=run_id).to_parquet(temp_path, index=False)
        temp_path.rename(final_path)
        written["tabular"] = final_path.relative_to(self.root).as_posix()
        return written

    def versions(self, source: str) -> dict[str, list[Path]]:
        """Every landed parquet per chunk key, oldest first."""
        by_chunk: dict[str, list[Path]] = {}
        for path in sorted((self.root / source).rglob("*.parquet")):
            key = path.parent.relative_to(self.root / source).as_posix()
            by_chunk.setdefault(key, []).append(path)
        return by_chunk

    def read_latest(self, source: str) -> pd.DataFrame:
        """All chunks of ``source``, taking only the newest version of each."""
        frames = [
            pd.read_parquet(paths[-1]).assign(chunk_key=key)
            for key, paths in self.versions(source).items()
        ]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
