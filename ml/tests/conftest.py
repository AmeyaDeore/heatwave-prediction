import json

import numpy as np
import pandas as pd
import pytest
import requests

from heatwave_ml.features import RiskCriteria, SeasonalNormals
from heatwave_ml.ingestion.http import HttpClient, RetryPolicy
from heatwave_ml.ingestion.regions import Region
from heatwave_ml.ingestion.settings import REPO_ROOT


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


TEST_REGIONS = [
    Region("mumbai", "Mumbai", "Mumbai City", "Maharashtra", "coastal", 18.975, 72.8258),
    Region("andheri", "Andheri", "Mumbai Suburban", "Maharashtra", "coastal", 19.1136, 72.8697),
]


@pytest.fixture
def regions():
    return list(TEST_REGIONS)


def build_fake_imd(regions=("mumbai", "andheri"), years=range(1991, 2021)) -> pd.DataFrame:
    """IMD-shaped Tmax history: a seasonal cycle peaking in spring, plus daily noise.
    The second region runs 1 °C warmer, so normals differ between regions."""
    dates = pd.date_range(f"{min(years)}-01-01", f"{max(years)}-12-31", freq="D")
    rng = np.random.default_rng(0)
    frames = []
    for offset, region in enumerate(regions):
        seasonal = 32 + offset + 3 * np.sin(2 * np.pi * (dates.dayofyear - 30) / 365.25)
        tmax = seasonal + rng.normal(0, 1.5, len(dates))
        frames.append(pd.DataFrame({"region_id": region, "date": dates, "tmax_c": tmax}))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="session")
def fake_imd():
    return build_fake_imd


@pytest.fixture(scope="session")
def fake_normals():
    return SeasonalNormals.from_imd(build_fake_imd())


@pytest.fixture(scope="session")
def criteria():
    return RiskCriteria.load(REPO_ROOT / "config" / "risk_classes.yaml")
