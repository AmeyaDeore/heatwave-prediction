"""In-process sliding-window rate limiting (Part 07 §4).

Protects predict, alert creation and login from a runaway poll loop or a brute-force
attempt. State is per process: fine for the single-node deployment this project targets;
behind several workers the effective limit is multiplied, and a shared store would be
needed (open item in docs/api/README.md).
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

from heatwave_api.errors import TooManyRequests


class RateLimiter:
    def __init__(
        self, limits_per_minute: dict[str, int], clock: Callable[[], float] = time.monotonic
    ):
        self.limits = limits_per_minute
        self.clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, client: str) -> None:
        limit = self.limits[bucket]
        now = self.clock()
        with self._lock:
            hits = self._hits[(bucket, client)]
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= limit:
                retry = max(1, int(60 - (now - hits[0])) + 1)
                raise TooManyRequests(
                    f"Too many requests. Try again in {retry} seconds.",
                    details={"limit_per_minute": limit, "retry_after_seconds": retry},
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)


def limit(bucket: str):
    """FastAPI dependency factory: ``Depends(limit("predict"))``."""

    def dependency(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        request.app.state.ctx.limiter.check(bucket, client)

    return dependency
