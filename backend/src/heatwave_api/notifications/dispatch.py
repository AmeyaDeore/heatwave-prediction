"""Where delivery runs (Part 09 §7): in the background, or inline.

background (default): issuing an alert stores every channel as PENDING and returns at
once; one worker thread delivers and writes each channel's outcome back to the
database, and the UI polls GET /api/v1/alerts/{id} (Part 13). One thread keeps
dispatch ordered and is plenty for a handful of officials. A real message queue (Redis,
SQS, ...) is the step up at larger scale: the job is already just "an alert id".

inline: the job runs inside the request, so the response already carries final
statuses. Used by tests and handy for debugging.

Crash safety: the PENDING rows are written before the job is queued, and on startup
every ISSUED alert with a PENDING channel is queued again (AlertService.resume_pending).
Delivery is therefore at-least-once: after a crash mid-send, a recipient may get the
same warning twice, which for a public-safety alert is the right side to err on.
"""

import logging
import queue
import threading
from collections.abc import Callable

log = logging.getLogger("heatwave_api.notifications")

_STOP = object()


class InlineDispatcher:
    mode = "inline"

    def __init__(self, job: Callable[[str], None]):
        self.job = job

    def submit(self, alert_id: str) -> None:
        self.job(alert_id)

    def join(self) -> None:
        pass

    def stop(self, timeout: float = 0) -> None:
        pass


class BackgroundDispatcher:
    mode = "background"

    def __init__(self, job: Callable[[str], None]):
        self.job = job
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="alert-dispatch", daemon=True)
        self._thread.start()

    def submit(self, alert_id: str) -> None:
        self._queue.put(alert_id)

    def join(self) -> None:
        """Block until every queued job has finished (tests, graceful shutdown)."""
        self._queue.join()

    def stop(self, timeout: float = 30.0) -> None:
        """Let queued jobs finish (up to `timeout`), then end the worker."""
        self._queue.put(_STOP)
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.warning(
                "dispatch worker still busy at shutdown; PENDING channels resume on restart"
            )

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                self.job(item)
            except Exception:  # a failed job must not kill the worker
                log.exception("dispatch job failed", extra={"alert_id": item})
            finally:
                self._queue.task_done()


Dispatcher = InlineDispatcher | BackgroundDispatcher


def make_dispatcher(mode: str, job: Callable[[str], None]) -> Dispatcher:
    return BackgroundDispatcher(job) if mode == "background" else InlineDispatcher(job)
