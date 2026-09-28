from datetime import date

import pandas as pd
import pytest

from heatwave_ml.ingestion.adapters.base import Chunk, FetchResult, NativePayload
from heatwave_ml.ingestion.http import SourceRequestError, SourceUnavailable
from heatwave_ml.ingestion.landing import RawLandingZone
from heatwave_ml.ingestion.pipeline import run_ingestion
from heatwave_ml.ingestion.quality import check_frame
from heatwave_ml.ingestion.runlog import IngestionLog


def frame_for(key: str, days: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region_id": key,
            "date": pd.date_range("2024-01-01", periods=days),
            "tmax_c": [30.0 + i for i in range(days)],
        }
    )


class ScriptedAdapter:
    """Returns, per chunk key, a frame or raises the scripted exception."""

    name = "scripted"
    key_columns = ("region_id", "date")
    continuous_dates = True

    def __init__(self, outcomes: dict):
        self.outcomes = outcomes
        self.fetched = []

    def fetch(self, chunk: Chunk) -> FetchResult:
        self.fetched.append(chunk.key)
        outcome = self.outcomes[chunk.key]
        if isinstance(outcome, Exception):
            raise outcome
        return FetchResult(frame=outcome, native=NativePayload(b"{}", "json"))


def chunks(*keys, resumable=True):
    return [Chunk(key, date(2024, 1, 1), date(2024, 1, 3), resumable=resumable) for key in keys]


@pytest.fixture
def zone(tmp_path):
    return RawLandingZone(tmp_path / "raw"), IngestionLog(tmp_path / "raw" / "_meta" / "log.jsonl")


def run(adapter, chunk_list, zone, force=False):
    landing, log = zone
    return run_ingestion(adapter, chunk_list, landing, log, job="test", request={}, force=force)


def test_success_lands_tabular_and_native_files_and_logs(zone):
    landing, log = zone
    result = run(ScriptedAdapter({"a": frame_for("a")}), chunks("a"), zone)

    assert result["status"] == "success" and result["records"] == 3
    assert len(list((landing.root / "scripted" / "a").glob("*.parquet"))) == 1
    assert len(list((landing.root / "scripted" / "a").glob("*.native.json"))) == 1
    assert [e["event"] for e in log.events()] == ["run_started", "chunk", "run_finished"]
    assert landing.read_latest("scripted")["tmax_c"].tolist() == [30.0, 31.0, 32.0]


def test_rerun_resumes_by_skipping_landed_chunks(zone):
    run(
        ScriptedAdapter({"a": frame_for("a"), "b": SourceUnavailable("down")}),
        chunks("a", "b"),
        zone,
    )
    adapter = ScriptedAdapter({"a": frame_for("a"), "b": frame_for("b")})

    result = run(adapter, chunks("a", "b"), zone)

    assert adapter.fetched == ["b"]  # "a" was not downloaded again
    assert result["counts"] == {"skipped": 1, "success": 1}


def test_force_refetch_lands_new_version_and_never_overwrites(zone):
    landing, _ = zone
    run(ScriptedAdapter({"a": frame_for("a")}), chunks("a"), zone)
    newer = frame_for("a").assign(tmax_c=40.0)

    run(ScriptedAdapter({"a": newer}), chunks("a"), zone, force=True)

    assert len(landing.versions("scripted")["a"]) == 2
    assert landing.read_latest("scripted")["tmax_c"].eq(40.0).all()


def test_non_resumable_chunks_are_always_fetched(zone):
    run(ScriptedAdapter({"f": frame_for("f")}), chunks("f", resumable=False), zone)
    adapter = ScriptedAdapter({"f": frame_for("f")})

    run(adapter, chunks("f", resumable=False), zone)

    assert adapter.fetched == ["f"]


def test_partial_failure_is_visible_and_distinguishes_retryable(zone):
    _, log = zone
    adapter = ScriptedAdapter(
        {
            "a": frame_for("a"),
            "b": SourceUnavailable("timeout"),
            "c": SourceRequestError("HTTP 422"),
        }
    )

    result = run(adapter, chunks("a", "b", "c"), zone)

    assert result["status"] == "partial"
    failed = {e["key"]: e for e in log.events() if e.get("status") == "failed"}
    assert failed["b"]["retryable"] is True
    assert failed["c"]["retryable"] is False


def test_all_failed_and_empty_statuses(zone):
    assert (
        run(ScriptedAdapter({"a": SourceUnavailable("x")}), chunks("a"), zone)["status"] == "failed"
    )
    assert run(ScriptedAdapter({"e": pd.DataFrame()}), chunks("e"), zone)["status"] == "empty"


def test_unexpected_exception_in_one_chunk_does_not_stop_others(zone):
    result = run(
        ScriptedAdapter({"a": RuntimeError("bug"), "b": frame_for("b")}), chunks("a", "b"), zone
    )

    assert result["counts"] == {"failed": 1, "success": 1}


def test_crashed_run_shows_as_incomplete(zone):
    _, log = zone
    log.append({"event": "run_started", "run_id": "r1", "source": "s", "job": "j"})

    assert log.runs()[0]["status"] == "incomplete"


def test_quality_flags_but_never_drops():
    frame = pd.DataFrame(
        {
            "region_id": ["a"] * 5,
            "date": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-05", "2024-01-06"]
            ),
            "tmax_c": [30.0, None, 31.0, 80.0, 29.0],
            "rh_pct": [50.0, 50.0, 50.0, 120.0, 50.0],
        }
    )

    report = check_frame(frame, ("region_id", "date"), continuous_dates=True)

    assert report["rows"] == 5
    assert report["nulls"] == {"tmax_c": 1}
    assert report["invalid"] == {"tmax_c": 1, "rh_pct": 1}
    assert report["duplicate_keys"] == 1
    assert report["date_gaps"]["a"]["missing_days"] == 2
    assert report["has_issues"]
