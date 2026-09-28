"""``heatwave-ingest``: the command-line entry point for Part 02.

    uv run heatwave-ingest historical --source nasa_power   # bulk training history (resumable)
    uv run heatwave-ingest historical --source imd          # IMD gridded Tmax, one file per year
    uv run heatwave-ingest recent                           # NASA POWER rolling recent window
    uv run heatwave-ingest forecast                         # next 1-3 days (schedule this)
    uv run heatwave-ingest synthetic                        # synthetic training batch
    uv run heatwave-ingest status                           # recent runs + landed coverage

Exit codes: 0 success/empty, 1 partial failure, 2 total failure. A scheduler or
operator can alert on anything non-zero.
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

from heatwave_ml.ingestion.adapters.imd import ImdGriddedTmaxAdapter
from heatwave_ml.ingestion.adapters.nasa_power import NasaPowerAdapter
from heatwave_ml.ingestion.adapters.open_meteo import OpenMeteoForecastAdapter
from heatwave_ml.ingestion.adapters.synthetic import SyntheticAdapter
from heatwave_ml.ingestion.http import HttpClient, RetryPolicy
from heatwave_ml.ingestion.landing import RawLandingZone
from heatwave_ml.ingestion.pipeline import run_ingestion
from heatwave_ml.ingestion.regions import load_regions
from heatwave_ml.ingestion.runlog import IngestionLog
from heatwave_ml.ingestion.settings import IngestionSettings

IST = timezone(timedelta(hours=5, minutes=30))
EXIT_CODES = {"success": 0, "empty": 0, "partial": 1, "failed": 2}
SOURCES = ("imd", "nasa_power", "open_meteo_forecast", "synthetic")


def _today() -> date:
    """Calendar day in India, which is what "today" and "next 3 days" mean here."""
    return datetime.now(IST).date()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="heatwave-ingest", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--regions", help="comma-separated region ids (default: all in config)")

    historical = sub.add_parser("historical", help="bulk historical pull for training")
    historical.add_argument("--source", choices=["nasa_power", "imd"], required=True)
    historical.add_argument("--start", type=date.fromisoformat, help="YYYY-MM-DD")
    historical.add_argument("--end", type=date.fromisoformat, help="YYYY-MM-DD")
    historical.add_argument("--force", action="store_true", help="re-fetch chunks already landed")
    add_common(historical)

    add_common(sub.add_parser("recent", help="NASA POWER rolling recent-days window"))

    forecast = sub.add_parser("forecast", help="next FORECAST_DAYS days from Open-Meteo")
    add_common(forecast)

    synthetic = sub.add_parser("synthetic", help="generate and land the synthetic batch")
    synthetic.add_argument("--count", type=int)
    synthetic.add_argument("--seed", type=int)
    synthetic.add_argument("--force", action="store_true")

    status = sub.add_parser("status", help="show recent runs and what is landed")
    status.add_argument("--last", type=int, default=10, help="number of runs to show")
    return parser.parse_args(argv)


def _print_status(settings: IngestionSettings, ingestion_log: IngestionLog, last: int) -> int:
    runs = ingestion_log.runs()[-last:]
    print(f"Ingestion log: {ingestion_log.path}")
    print(f"\nLast {len(runs)} run(s):")
    for run in runs:
        counts = ", ".join(f"{k}={v}" for k, v in run.get("counts", {}).items())
        print(
            f"  {run['run_id']}  {run.get('source', '?'):<20} {run.get('job', '?'):<10} "
            f"{run.get('status', '?'):<10} records={run.get('records', 0):<7} {counts}"
        )
        for chunk in run["chunks"]:
            if chunk["status"] == "failed":
                print(f"      FAILED {chunk['key']}: {chunk['error'][:160]}")

    landing = RawLandingZone(settings.raw_data_dir)
    print(f"\nLanded in {settings.raw_data_dir}:")
    for source in SOURCES:
        versions = landing.versions(source)
        refetched = sum(1 for paths in versions.values() if len(paths) > 1)
        print(f"  {source:<20} chunks={len(versions):<5} chunks_with_multiple_versions={refetched}")

    latest = runs[-1]["status"] if runs else "success"
    return EXIT_CODES.get(latest, 2)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = IngestionSettings.from_env()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ingestion_log = IngestionLog(settings.raw_data_dir / "_meta" / "ingestion_log.jsonl")
    if args.command == "status":
        return _print_status(settings, ingestion_log, args.last)

    only = args.regions.split(",") if getattr(args, "regions", None) else None
    regions = load_regions(settings.regions_file, only)
    http = HttpClient(
        RetryPolicy(settings.max_attempts, settings.backoff_base_seconds),
        settings.http_timeout_seconds,
    )
    today = _today()
    request: dict = {"regions": [r.id for r in regions]}
    force = getattr(args, "force", False)

    if args.command == "historical" and args.source == "nasa_power":
        adapter = NasaPowerAdapter(http, settings.nasa_power_base_url)
        start, end = args.start or settings.training_start, args.end or settings.training_end
        chunks = adapter.historical_chunks(regions, start, end, today)
        request |= {"start": start, "end": end}
    elif args.command == "historical":
        adapter = ImdGriddedTmaxAdapter(
            http, settings.imd_tmax_url, settings.imd_inbox_dir, regions, settings.imd_fetch_mode
        )
        start_year = args.start.year if args.start else settings.imd_history_start_year
        end_year = args.end.year if args.end else settings.training_end.year
        chunks = adapter.year_chunks(start_year, end_year, today)
        request |= {"start_year": start_year, "end_year": end_year, "mode": settings.imd_fetch_mode}
    elif args.command == "recent":
        adapter = NasaPowerAdapter(http, settings.nasa_power_base_url)
        chunks = adapter.recent_chunks(regions, settings.nasa_power_recent_days, today)
        request |= {"days": settings.nasa_power_recent_days}
    elif args.command == "forecast":
        adapter = OpenMeteoForecastAdapter(http, settings.open_meteo_forecast_url)
        chunks = adapter.forecast_chunks(regions, today, settings.forecast_days)
        request |= {"issued_for": today, "days": settings.forecast_days}
    else:
        adapter = SyntheticAdapter(
            regions,
            count=args.count or settings.synthetic_record_count,
            seed=args.seed if args.seed is not None else settings.random_seed,
            start=settings.training_start,
            end=settings.training_end,
        )
        chunks = adapter.chunks()
        request |= {
            "count": adapter.count,
            "seed": adapter.seed,
            "generator": adapter.generator_version,
        }

    result = run_ingestion(
        adapter,
        chunks,
        RawLandingZone(settings.raw_data_dir),
        ingestion_log,
        job=args.command,
        request=request,
        force=force,
    )
    print(
        f"{adapter.name}: {result['status']} ({result['counts']}, {result['records']} records) "
        f"run_id={result['run_id']}"
    )
    if result["status"] in {"partial", "failed"}:
        print("See failures with: uv run heatwave-ingest status", file=sys.stderr)
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
