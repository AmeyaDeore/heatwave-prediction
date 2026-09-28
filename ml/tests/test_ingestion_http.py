import pytest
import requests
from conftest import make_response

from heatwave_ml.ingestion.http import RetryPolicy, SourceRequestError, SourceUnavailable


def test_retries_transient_errors_then_succeeds(fake_http):
    client, session = fake_http(
        requests.ConnectionError("reset"), make_response(503), make_response(200, b"ok")
    )

    assert client.request("GET", "https://x").content == b"ok"
    assert len(session.calls) == 3


def test_gives_up_after_max_attempts_as_unavailable(fake_http):
    client, session = fake_http(make_response(502), make_response(502), make_response(502))

    with pytest.raises(SourceUnavailable, match="gave up after 3 attempts: HTTP 502"):
        client.request("GET", "https://x")
    assert len(session.calls) == 3


def test_client_errors_are_not_retried(fake_http):
    client, session = fake_http(make_response(422, b"bad date"))

    with pytest.raises(SourceRequestError, match="HTTP 422"):
        client.request("GET", "https://x")
    assert len(session.calls) == 1


def test_backoff_is_exponential_capped_and_honours_retry_after():
    policy = RetryPolicy(backoff_base_seconds=2, backoff_max_seconds=10)

    assert [policy.delay(a) for a in (1, 2, 3, 4)] == [2, 4, 8, 10]
    assert policy.delay(1, retry_after="7") == 7
