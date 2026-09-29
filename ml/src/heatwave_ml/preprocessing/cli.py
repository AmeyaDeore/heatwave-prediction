"""``heatwave-prepare``: the command-line entry point for Part 03.

    uv run heatwave-prepare normals    # IMD 1991-2020 → config/seasonal_normals.csv
    uv run heatwave-prepare dataset    # synthetic → data/heatwave_dataset.csv (+ manifest)
    uv run heatwave-prepare observed   # IMD + NASA history → data/processed/observed_dataset.*
    uv run heatwave-prepare sample     # latest forecast → data/sample/forecast_features.csv
    uv run heatwave-prepare all        # the four above, in order

Every step is deterministic: the same raw input and seed give byte-identical output.
"""

import argparse
import json
import logging
import os
import sys

from heatwave_ml.features.criteria import RiskCriteria
from heatwave_ml.features.normals import SeasonalNormals
from heatwave_ml.ingestion.adapters.synthetic import SyntheticAdapter
from heatwave_ml.ingestion.landing import RawLandingZone
from heatwave_ml.ingestion.pipeline import run_ingestion
from heatwave_ml.ingestion.regions import load_regions
from heatwave_ml.ingestion.runlog import IngestionLog
from heatwave_ml.ingestion.settings import IngestionSettings
from heatwave_ml.preprocessing.dataset import (
    build_forecast_sample,
    build_observed_dataset,
    prepare_modeling_dataset,
    sha256_of,
    write_dataset,
)
from heatwave_ml.preprocessing.settings import PreparationSettings
from heatwave_ml.preprocessing.synthetic import SyntheticGeneratorV1

log = logging.getLogger("heatwave_ml.prepare")


def _normals(ingest: IngestionSettings, prep: PreparationSettings) -> int:
    imd = RawLandingZone(ingest.raw_data_dir).read_latest("imd")
    if imd.empty:
        print(
            "No IMD data landed. Run: uv run heatwave-ingest historical --source imd",
            file=sys.stderr,
        )
        return 2
    normals = SeasonalNormals.from_imd(imd)
    normals.save(prep.seasonal_normals_file)
    summary = normals.table.groupby("region_id")["normal_tmax_c"].agg(["min", "max"])
    print(f"Seasonal normals → {prep.seasonal_normals_file} ({len(normals.table)} rows)")
    print(summary.to_string())
    return 0


def _dataset(ingest: IngestionSettings, prep: PreparationSettings, args) -> int:
    criteria = RiskCriteria.load(prep.risk_config)
    normals = SeasonalNormals.load(prep.seasonal_normals_file)
    regions = load_regions(ingest.regions_file)
    zone = RawLandingZone(ingest.raw_data_dir)

    # Land the batch through Part 02's pipeline (skipped if this generator+seed+count
    # is already landed), so it gets the same immutable storage and run log entry.
    adapter = SyntheticAdapter(
        regions,
        count=args.count or ingest.synthetic_record_count,
        seed=prep.random_seed if args.seed is None else args.seed,
        start=ingest.training_start,
        end=ingest.training_end,
        generator=SyntheticGeneratorV1(normals, criteria),
    )
    [chunk] = adapter.chunks()
    result = run_ingestion(
        adapter,
        [chunk],
        zone,
        IngestionLog(ingest.raw_data_dir / "_meta" / "ingestion_log.jsonl"),
        job="synthetic",
        request={
            "count": adapter.count,
            "seed": adapter.seed,
            "generator": adapter.generator_version,
        },
        force=args.force,
    )
    if result["status"] != "success":
        print(f"Landing the synthetic batch failed: {result}", file=sys.stderr)
        return 2
    landed_file = zone.versions(adapter.name)[chunk.key][-1]
    raw = zone.read_latest(adapter.name)
    raw = raw[raw["chunk_key"] == chunk.key]

    dataset, manifest = prepare_modeling_dataset(
        raw,
        normals,
        criteria,
        regions,
        test_fraction=prep.test_fraction,
        validation_fraction=prep.validation_fraction,
        seed=prep.random_seed,
    )
    manifest = {
        "synthetic": {
            "generator": adapter.generator_version,
            "seed": adapter.seed,
            "records_generated": adapter.count,
            "landed_file": landed_file.relative_to(ingest.raw_data_dir).as_posix(),
            "date_range": [str(ingest.training_start), str(ingest.training_end)],
        },
        "seasonal_normals": {
            "file": prep.seasonal_normals_file.name,
            "sha256": sha256_of(prep.seasonal_normals_file),
        },
        **manifest,
    }
    manifest = write_dataset(dataset, manifest, prep.dataset_path, prep.manifest_path)

    print(f"Modelling dataset → {prep.dataset_path} ({manifest['rows']} rows)")
    print(f"Manifest          → {prep.manifest_path}")
    print(f"Rows: {manifest['cleaning']['rows_in']} generated → {manifest['rows']} after cleaning")
    for name, dist in manifest["split"]["class_distribution"].items():
        print(f"  {name:<10} {dist['rows']:>5}  {dist['counts']}")
    print(f"Label vs rule on observed features: {manifest['label_vs_rule_on_observed_features']}")
    return 0


def _observed(ingest: IngestionSettings, prep: PreparationSettings) -> int:
    zone = RawLandingZone(ingest.raw_data_dir)
    imd, nasa = zone.read_latest("imd"), zone.read_latest("nasa_power")
    if imd.empty or nasa.empty:
        print(
            "Needs landed IMD and NASA POWER history (heatwave-ingest historical).", file=sys.stderr
        )
        return 2
    dataset, summary = build_observed_dataset(
        imd,
        nasa,
        SeasonalNormals.load(prep.seasonal_normals_file),
        RiskCriteria.load(prep.risk_config),
        load_regions(ingest.regions_file),
    )
    prep.processed_dir.mkdir(parents=True, exist_ok=True)
    path = prep.processed_dir / "observed_dataset.parquet"
    dataset.to_parquet(path, index=False)
    (prep.processed_dir / "observed_dataset.summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"Observed reference dataset → {path} ({summary['rows']} rows)")
    print(f"  class distribution: {summary['class_distribution']['counts']}")
    print(
        f"  max Tmax {summary['tmax_c_max']} °C, max deviation {summary['temp_deviation_c_max']} °C"
    )
    return 0


def _sample(ingest: IngestionSettings, prep: PreparationSettings) -> int:
    forecast = RawLandingZone(ingest.raw_data_dir).read_latest("open_meteo_forecast")
    if forecast.empty:
        print("No forecast landed. Run: uv run heatwave-ingest forecast", file=sys.stderr)
        return 2
    sample = build_forecast_sample(forecast, SeasonalNormals.load(prep.seasonal_normals_file))
    prep.sample_dir.mkdir(parents=True, exist_ok=True)
    path = prep.sample_dir / "forecast_features.csv"
    sample.assign(date=sample["date"].dt.strftime("%Y-%m-%d")).to_csv(
        path, index=False, lineterminator="\n"
    )
    print(f"Forecast feature sample → {path} ({len(sample)} rows)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heatwave-prepare", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("normals", help="derive seasonal normals from landed IMD history")
    for name in ("dataset", "all"):
        p = sub.add_parser(
            name, help="build the modelling dataset" if name == "dataset" else "every step"
        )
        p.add_argument(
            "--count", type=int, help="synthetic records (default SYNTHETIC_RECORD_COUNT)"
        )
        p.add_argument("--seed", type=int, help="generator seed (default RANDOM_SEED)")
        p.add_argument("--force", action="store_true", help="re-land the synthetic batch")
    sub.add_parser("observed", help="build the real-history reference dataset")
    sub.add_parser("sample", help="write forecast features to data/sample/")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ingest, prep = IngestionSettings.from_env(), PreparationSettings.from_env()

    if args.command == "normals":
        return _normals(ingest, prep)
    if args.command == "dataset":
        return _dataset(ingest, prep, args)
    if args.command == "observed":
        return _observed(ingest, prep)
    if args.command == "sample":
        return _sample(ingest, prep)
    for step in (
        lambda: _normals(ingest, prep),
        lambda: _dataset(ingest, prep, args),
        lambda: _observed(ingest, prep),
        lambda: _sample(ingest, prep),
    ):
        if code := step():
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
