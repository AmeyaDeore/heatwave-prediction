"""Run one adapter over a list of chunks: skip what's landed, fetch, check, land, log.

A failed chunk never stops the others. The run's overall status makes partial
failure visible instead of letting it pass as a smaller dataset:

    success  every chunk landed or was already landed (empty chunks allowed)
    empty    nothing failed, but the source returned no data at all
    partial  some chunks failed and some did not
    failed   every chunk failed
"""

import logging
import uuid
from datetime import UTC, datetime

from heatwave_ml.ingestion.adapters.base import Chunk, SourceAdapter
from heatwave_ml.ingestion.http import SourceRequestError, SourceUnavailable
from heatwave_ml.ingestion.landing import RawLandingZone
from heatwave_ml.ingestion.quality import check_frame
from heatwave_ml.ingestion.runlog import IngestionLog

log = logging.getLogger(__name__)


def new_run_id(now: datetime | None = None) -> str:
    """Sortable by time: readers pick the newest landed version by run_id order."""
    now = now or datetime.now(UTC)
    return f"{now:%Y%m%dT%H%M%S.%fZ}-{uuid.uuid4().hex[:6]}"


def _overall_status(statuses: list[str]) -> str:
    failed = statuses.count("failed")
    if failed and failed == len(statuses):
        return "failed"
    if failed:
        return "partial"
    if statuses and all(s == "empty" for s in statuses):
        return "empty"
    return "success"


def run_ingestion(
    adapter: SourceAdapter,
    chunks: list[Chunk],
    landing: RawLandingZone,
    ingestion_log: IngestionLog,
    *,
    job: str,
    request: dict,
    force: bool = False,
) -> dict:
    run_id = new_run_id()
    started_at = datetime.now(UTC)
    ingestion_log.append(
        {
            "event": "run_started",
            "run_id": run_id,
            "source": adapter.name,
            "job": job,
            "request": request,
            "chunk_count": len(chunks),
            "started_at": started_at.isoformat(),
        }
    )

    statuses = []
    records = 0
    for chunk in chunks:
        event = {"event": "chunk", "run_id": run_id, "source": adapter.name, "key": chunk.key}
        if chunk.resumable and not force and landing.has(adapter.name, chunk.key):
            event |= {"status": "skipped", "reason": "already landed (use --force to re-fetch)"}
        else:
            try:
                result = adapter.fetch(chunk)
            except SourceUnavailable as exc:
                event |= {"status": "failed", "retryable": True, "error": str(exc)}
            except SourceRequestError as exc:
                event |= {"status": "failed", "retryable": False, "error": str(exc)}
            except Exception as exc:  # a bug in one chunk must not hide the others' results
                log.exception("Unexpected error in chunk %s", chunk.key)
                event |= {"status": "failed", "retryable": False, "error": repr(exc)}
            else:
                if result.frame.empty:
                    event |= {"status": "empty", "records": 0, "notes": result.notes}
                else:
                    quality = check_frame(
                        result.frame, adapter.key_columns, adapter.continuous_dates
                    )
                    files = landing.write(adapter.name, chunk.key, run_id, result)
                    event |= {
                        "status": "success",
                        "records": len(result.frame),
                        "files": files,
                        "quality": quality,
                        "notes": result.notes,
                    }

        event["at"] = datetime.now(UTC).isoformat()
        ingestion_log.append(event)
        statuses.append(event["status"])
        records += event.get("records", 0)
        log.info("%s %s: %s", adapter.name, chunk.key, event["status"])

    finished = {
        "event": "run_finished",
        "run_id": run_id,
        "status": _overall_status(statuses),
        "counts": {s: statuses.count(s) for s in sorted(set(statuses))},
        "records": records,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    ingestion_log.append(finished)
    return finished
