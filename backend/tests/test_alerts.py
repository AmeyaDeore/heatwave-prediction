"""Alerts: auth gate, draft-to-issued flow, idempotency, per-channel delivery status."""

import pytest
from api_support import PASSWORD, new_alert

from heatwave_api.notifications import DeliveryResult, MockNotifier

ALERTS = "/api/v1/alerts"


class RecordingNotifier(MockNotifier):
    def __init__(self, fail=(), crash=()):
        super().__init__(list(fail))
        self.crash = set(crash)
        self.sent: list[tuple[str, str]] = []

    def send(self, alert, channel) -> DeliveryResult:
        self.sent.append((alert["code"], channel))
        if channel in self.crash:
            raise ConnectionError("provider socket closed")
        return super().send(alert, channel)


@pytest.fixture
def notifier(client):
    client.app.state.services.notifier = RecordingNotifier()
    return client.app.state.services.notifier


def statuses(alert: dict) -> dict:
    return {c["channel"]: c["status"] for c in alert["channels"]}


def test_writes_need_a_signed_in_user(client):
    response = client.post(ALERTS, json=new_alert())
    assert response.status_code == 401
    assert response.json()["error"]["category"] == "auth"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    garbage = {"Authorization": "Bearer not.a.token"}
    assert client.post(ALERTS, json=new_alert(), headers=garbage).status_code == 401
    assert client.patch(f"{ALERTS}/HW-2026-0001", json={"status": "ISSUED"}).status_code == 401
    assert client.get(ALERTS).json()["data"]["total"] == 0


def test_save_as_draft_then_issue_on_the_same_record(notifier, client, auth):
    response = client.post(ALERTS, json=new_alert(), headers=auth)
    assert response.status_code == 201, response.text
    draft = response.json()["data"]
    assert draft["alert_id"] == "HW-2026-0001"
    assert draft["status"] == "DRAFT" and draft["issued_at"] is None
    assert set(statuses(draft).values()) == {"READY"}
    assert draft["created_by"] == {"username": "officer", "display_name": "Duty Officer"}
    assert response.headers["Location"] == "/api/v1/alerts/HW-2026-0001"
    assert notifier.sent == []  # a draft never notifies anyone

    edited = client.patch(
        f"{ALERTS}/HW-2026-0001",
        json={"message": "Updated advisory text.", "channels": ["GOVERNMENT_PORTAL"]},
        headers=auth,
    ).json()["data"]
    assert edited["message"] == "Updated advisory text."
    assert statuses(edited) == {"GOVERNMENT_PORTAL": "READY"}
    assert notifier.sent == []

    ready = client.patch(f"{ALERTS}/HW-2026-0001", json={"status": "READY"}, headers=auth)
    assert ready.json()["data"]["status"] == "READY" and notifier.sent == []

    issued = client.patch(f"{ALERTS}/HW-2026-0001", json={"status": "ISSUED"}, headers=auth)
    assert issued.status_code == 200
    alert = issued.json()["data"]
    assert alert["alert_id"] == "HW-2026-0001"  # same record, status changed
    assert alert["status"] == "ISSUED" and alert["issued_at"]
    assert alert["issued_by"]["username"] == "officer"
    assert statuses(alert) == {"GOVERNMENT_PORTAL": "NOTIFIED"}
    assert alert["channels"][0]["attempts"] == 1
    assert notifier.sent == [("HW-2026-0001", "GOVERNMENT_PORTAL")]
    assert issued.json()["meta"]["warnings"] == []


def test_an_issued_alert_is_locked(client, auth):
    client.post(ALERTS, json=new_alert(status="ISSUED"), headers=auth)
    for change in ({"message": "edit"}, {"status": "DRAFT"}, {"status": "ISSUED"}):
        response = client.patch(f"{ALERTS}/HW-2026-0001", json=change, headers=auth)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ALERT_ALREADY_ISSUED"


def test_a_failed_channel_is_visible_and_does_not_block_the_others(client, auth):
    client.app.state.services.notifier = RecordingNotifier(
        fail={"EMERGENCY_SERVICES"}, crash={"GOVERNMENT_PORTAL"}
    )
    response = client.post(ALERTS, json=new_alert(status="ISSUED"), headers=auth)
    assert response.status_code == 201
    body = response.json()
    alert = body["data"]
    assert statuses(alert) == {
        "PUBLIC_MOBILE_ALERT": "NOTIFIED",
        "GOVERNMENT_PORTAL": "FAILED",
        "EMERGENCY_SERVICES": "FAILED",
    }
    assert alert["delivery_summary"] == {"READY": 0, "PENDING": 0, "NOTIFIED": 1, "FAILED": 2}
    errors = {c["channel"]: c["last_error"] for c in alert["channels"]}
    assert errors["GOVERNMENT_PORTAL"] == "Delivery error (ConnectionError)"
    assert "configured to fail" in errors["EMERGENCY_SERVICES"]
    assert len(body["meta"]["warnings"]) == 2
    assert any("Emergency Services" in w for w in body["meta"]["warnings"])
    # ... and the record still says so later.
    stored = client.get(f"{ALERTS}/HW-2026-0001").json()["data"]
    assert statuses(stored) == statuses(alert)


def test_a_retried_submission_does_not_create_a_second_alert(notifier, client, auth):
    body = new_alert(status="ISSUED")
    first = client.post(ALERTS, json=body, headers=auth)
    again = client.post(ALERTS, json=body, headers=auth)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["meta"]["idempotent_replay"] is True
    assert first.json()["meta"]["idempotent_replay"] is False
    assert again.json()["data"]["alert_id"] == first.json()["data"]["alert_id"]
    assert len(notifier.sent) == 3  # dispatched once, not twice
    assert client.get(ALERTS).json()["data"]["total"] == 1

    reused = client.post(ALERTS, json=body | {"message": "different"}, headers=auth)
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    fresh = client.post(ALERTS, json=new_alert(), headers=auth)
    assert fresh.json()["data"]["alert_id"] == "HW-2026-0002"


def test_alert_list_filters_and_pages(client, auth):
    client.post(ALERTS, json=new_alert(region_id="kurla"), headers=auth)
    client.post(ALERTS, json=new_alert(status="ISSUED"), headers=auth)
    client.post(ALERTS, json=new_alert(status="READY"), headers=auth)
    page = client.get(ALERTS).json()["data"]
    assert page["total"] == 3
    assert [a["alert_id"] for a in page["items"]] == [
        "HW-2026-0003",
        "HW-2026-0002",
        "HW-2026-0001",
    ]
    issued = client.get(f"{ALERTS}?status=ISSUED").json()["data"]
    assert [a["alert_id"] for a in issued["items"]] == ["HW-2026-0002"]
    kurla = client.get(f"{ALERTS}?region_id=kurla").json()["data"]
    assert [a["region"]["name"] for a in kurla["items"]] == ["Kurla"]
    second = client.get(f"{ALERTS}?limit=1&offset=1").json()["data"]
    assert [a["alert_id"] for a in second["items"]] == ["HW-2026-0002"]
    assert client.get(f"{ALERTS}?status=SENT").status_code == 422
    assert client.get(f"{ALERTS}?limit=0").status_code == 422


def test_unknown_alert(client):
    response = client.get(f"{ALERTS}/HW-2026-0099")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALERT_NOT_FOUND"
    assert client.get(f"{ALERTS}/../../etc").status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"channels": []},
        {"channels": ["PUBLIC_MOBILE_ALERT", "PUBLIC_MOBILE_ALERT"]},
        {"channels": ["CARRIER_PIGEON"]},
        {"severity": "EXTREME"},
        {"status": "SENT"},
        {"message": ""},
        {"message": "x" * 1001},
        {"client_request_id": "not-a-uuid"},
        {"region_id": None},
    ],
)
def test_invalid_alert_input(client, auth, change):
    response = client.post(ALERTS, json=new_alert() | change, headers=auth)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_an_empty_patch_and_an_unknown_region_are_rejected(client, auth):
    client.post(ALERTS, json=new_alert(), headers=auth)
    assert client.patch(f"{ALERTS}/HW-2026-0001", json={}, headers=auth).status_code == 422
    response = client.post(ALERTS, json=new_alert(region_id="atlantis"), headers=auth)
    assert response.json()["error"]["code"] == "UNKNOWN_REGION"


def test_an_alert_can_cite_the_prediction_behind_it(client, auth):
    prediction = client.post("/api/v1/predict", json={"region_id": "mumbai"}).json()["data"]
    pid = prediction["prediction_id"]
    alert = client.post(ALERTS, json=new_alert(prediction_id=pid), headers=auth).json()["data"]
    assert alert["prediction_id"] == pid

    unknown = client.post(ALERTS, json=new_alert(prediction_id="f" * 32), headers=auth)
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "UNKNOWN_PREDICTION"
    wrong_region = client.post(
        ALERTS, json=new_alert(region_id="kurla", prediction_id=pid), headers=auth
    )
    assert wrong_region.json()["error"]["code"] == "PREDICTION_REGION_MISMATCH"
    moved = client.patch(f"{ALERTS}/{alert['alert_id']}", json={"region_id": "kurla"}, headers=auth)
    assert moved.json()["error"]["code"] == "PREDICTION_REGION_MISMATCH"


def test_alert_writes_are_rate_limited(make_client, user):
    client = make_client(rate_limit_alert_writes="1/minute")
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "officer", "password": PASSWORD},
    ).json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(ALERTS, json=new_alert(), headers=headers).status_code == 201
    assert client.post(ALERTS, json=new_alert(), headers=headers).status_code == 429
