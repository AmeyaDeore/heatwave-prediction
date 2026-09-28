"""HTTP with a bounded retry policy.

Failures are split into two kinds, because the pipeline treats them differently:

- ``SourceUnavailable``: transient (network error, timeout, 408/425/429/5xx). The
  request is retried with exponential backoff, and this is raised only once the
  attempts are used up. Re-running the pipeline later is the right response.
- ``SourceRequestError``: permanent (any other 4xx, or a response we cannot use).
  It is not retried, because retrying would get the same answer.

"Source returned no data" is neither: adapters return an empty frame for it.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class SourceUnavailable(Exception):
    """The source could not be reached after every retry. Safe to retry later."""


class SourceRequestError(Exception):
    """The source rejected the request or sent unusable data. Retrying will not help."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0

    def delay(self, attempt: int, retry_after: str | None = None) -> float:
        delay = self.backoff_base_seconds * 2 ** (attempt - 1)
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        return min(delay, self.backoff_max_seconds)


class HttpClient:
    def __init__(
        self,
        policy: RetryPolicy,
        timeout_seconds: float,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.policy = policy
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.sleep = sleep

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_error = ""
        for attempt in range(1, self.policy.max_attempts + 1):
            retry_after = None
            try:
                response = self.session.request(method, url, timeout=self.timeout_seconds, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in RETRYABLE_STATUS:
                    raise SourceRequestError(
                        f"HTTP {response.status_code} from {url}: {response.text[:300]}"
                    )
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After")

            if attempt < self.policy.max_attempts:
                delay = self.policy.delay(attempt, retry_after)
                log.warning(
                    "%s %s failed (%s); attempt %d/%d, retrying in %.1fs",
                    method,
                    url,
                    last_error,
                    attempt,
                    self.policy.max_attempts,
                    delay,
                )
                self.sleep(delay)

        raise SourceUnavailable(
            f"{url} gave up after {self.policy.max_attempts} attempts: {last_error}"
        )
