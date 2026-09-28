import json

import pytest
import requests

from heatwave_ml.ingestion.http import HttpClient, RetryPolicy
from heatwave_ml.ingestion.regions import Region


def make_response(status: int = 200, body: bytes | dict = b"", headers: dict | None = None):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode() if isinstance(body, dict) else body
    response.headers.update(headers or {})
    return response


class FakeSession:
    """Plays back queued responses (or raises queued exceptions) and records every call."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def fake_http():
    def build(*outcomes, max_attempts=3):
        session = FakeSession(*outcomes)
        client = HttpClient(
            RetryPolicy(max_attempts, 0.01), 5, session=session, sleep=lambda _: None
        )
        return client, session

    return build


@pytest.fixture
def regions():
    return [
        Region("mumbai", "Mumbai", "Mumbai City", "Maharashtra", "coastal", 18.975, 72.8258),
        Region("andheri", "Andheri", "Mumbai Suburban", "Maharashtra", "coastal", 19.1136, 72.8697),
    ]
