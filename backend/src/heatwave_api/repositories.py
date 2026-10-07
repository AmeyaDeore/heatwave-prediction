"""Persistence interfaces (Part 07 ↔ Part 08).

The API depends on this Protocol, never on a database. The service uses Part 08's
`SqliteRepository` (db/repository.py). `MemoryRepository` is a test double kept for unit
tests that want no database at all; it loses everything on restart.
"""

import threading
from datetime import datetime
from typing import Protocol

from heatwave_api.schemas import AlertOut, ModelPerformance, PredictionOut


class Repository(Protocol):
    # predictions (append-only: never updated or deleted, Part 08 §5)
    def add_prediction(self, prediction: PredictionOut) -> None: ...

    def get_prediction(self, prediction_id: str) -> PredictionOut | None: ...

    def latest_prediction(self, region_id: str, lead_days: int) -> PredictionOut | None: ...

    def predictions_since(
        self, since: datetime, region_id: str | None = None
    ) -> list[PredictionOut]: ...

    # alerts
    def next_alert_sequence(self, year: int) -> int: ...

    def save_alert(self, alert: AlertOut, request_key: tuple[str, str] | None = None) -> None: ...

    def get_alert(self, alert_id: str) -> AlertOut | None: ...

    def find_alert_by_request(self, user_id: str, client_request_id: str) -> AlertOut | None: ...

    def list_alerts(
        self, *, status: str | None, region_id: str | None, limit: int, offset: int
    ) -> tuple[list[AlertOut], int]: ...

    # model metadata (the version the service loaded, and its Part 05 metrics)
    def record_active_model(self, perf: ModelPerformance) -> None: ...

    def active_model(self) -> ModelPerformance | None: ...

    def ping(self) -> bool: ...


class MemoryRepository:
    def __init__(self):
        self._lock = threading.RLock()
        self._predictions: dict[str, PredictionOut] = {}
        self._alerts: dict[str, AlertOut] = {}
        self._requests: dict[tuple[str, str], str] = {}
        self._sequence: dict[int, int] = {}
        self._model: ModelPerformance | None = None

    def add_prediction(self, prediction: PredictionOut) -> None:
        with self._lock:
            self._predictions[prediction.prediction_id] = prediction

    def get_prediction(self, prediction_id: str) -> PredictionOut | None:
        return self._predictions.get(prediction_id)

    def latest_prediction(self, region_id: str, lead_days: int) -> PredictionOut | None:
        with self._lock:
            matches = [
                p
                for p in self._predictions.values()
                if p.region.id == region_id and p.forecast_window.lead_days == lead_days
            ]
        return max(matches, key=lambda p: p.created_at, default=None)

    def predictions_since(
        self, since: datetime, region_id: str | None = None
    ) -> list[PredictionOut]:
        with self._lock:
            found = [
                p
                for p in self._predictions.values()
                if p.created_at >= since and (region_id is None or p.region.id == region_id)
            ]
        return sorted(found, key=lambda p: p.created_at)

    def next_alert_sequence(self, year: int) -> int:
        with self._lock:
            self._sequence[year] = self._sequence.get(year, 0) + 1
            return self._sequence[year]

    def save_alert(self, alert: AlertOut, request_key: tuple[str, str] | None = None) -> None:
        with self._lock:
            self._alerts[alert.alert_id] = alert
            if request_key is not None:
                self._requests[request_key] = alert.alert_id

    def get_alert(self, alert_id: str) -> AlertOut | None:
        return self._alerts.get(alert_id)

    def find_alert_by_request(self, user_id: str, client_request_id: str) -> AlertOut | None:
        alert_id = self._requests.get((user_id, client_request_id))
        return self._alerts.get(alert_id) if alert_id else None

    def list_alerts(
        self, *, status: str | None, region_id: str | None, limit: int, offset: int
    ) -> tuple[list[AlertOut], int]:
        with self._lock:
            found = [
                a
                for a in self._alerts.values()
                if (status is None or a.status == status)
                and (region_id is None or a.region.id == region_id)
            ]
        found.sort(key=lambda a: a.created_at, reverse=True)
        return found[offset : offset + limit], len(found)

    def record_active_model(self, perf: ModelPerformance) -> None:
        self._model = perf

    def active_model(self) -> ModelPerformance | None:
        return self._model

    def ping(self) -> bool:
        return True
