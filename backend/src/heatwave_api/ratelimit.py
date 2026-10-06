"""A fixed-window rate limiter, per client address and per bucket (Part 07 §4).

In-process memory: each worker counts on its own, and a restart resets the counts.
That is enough for what it is for (a misbehaving poll loop or a password-guessing
script), and it keeps the service free of shared state. Behind a reverse proxy the
client address is the proxy's unless the server is started with --proxy-headers
(Part 18).
"""

import math
import threading
import time


class RateLimiter:
    MAX_KEYS = 10_000

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str, limit: int, period_s: int) -> int | None:
        """Count one request. None if allowed, else seconds until the window resets."""
        if limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            if len(self._windows) > self.MAX_KEYS:
                self._windows = {k: v for k, v in self._windows.items() if now - v[0] < period_s}
            start, count = self._windows.get((bucket, key), (now, 0))
            if now - start >= period_s:
                start, count = now, 0
            if count >= limit:
                return max(1, math.ceil(period_s - (now - start)))
            self._windows[(bucket, key)] = (start, count + 1)
            return None
