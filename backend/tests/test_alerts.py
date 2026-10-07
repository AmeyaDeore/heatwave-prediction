import re
from uuid import uuid4

from fakes import FakePredictor  # noqa: F401  (documents which double the fixtures use)

from heatwave_api.notifier import DeliveryResult

MESSAGE = "Heatwave conditions expected. Stay indoors between noon and 4 PM."


def body(**overrides):
    return {
        "client_request_id": str(uuid4()),
        "region_id": "mumbai",
        "severity": "HEATWAVE",
        "message": MESSAGE,
        "channels": ["public_mobile", "hospitals"],
        **overrides,
    }


def create(client, auth, **overrides):
    return client.post("/api/v1/alerts", json=body(**overrides), headers=auth)


def test_writes_require_a_token(client):
    assert client.post("/api/v1/alerts", json=body()).status_code == 401
    assert client.patch("/api/v1/alerts/HW-2026-0001", json={"status": "READY"}).status_code == 401
    r = client.post("/api/v1/alerts", json=body(), headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


def test_reads_are_open(client):
    assert client.get("/api/v1/alerts").status_code == 200


def test_default_is_a_draft_with_ready_channels_and_nothing_sent(client, auth, notifier):
    r = create(client, auth)
    assert r.status_code == 201
    alert = r.json()["data"]
    assert alert["status"] == "DRAFT"
    assert alert["issued_at"] is None
    assert {c["status"] for c in alert["channels"]} == {"READY"}
    assert notifier.sent == []


def test_alert_id_is_code_year_sequence(client, auth):
    first = create(client, auth).json()["data"]["alert_id"]
    second = create(client, auth).json()["data"]["alert_id"]
    assert re.fullmatch(r"HW-\d{4}-0001", first)
    assert second.endswith("-0002")


def test_issue_immediately_notifies_every_channel(client, auth, notifier):
    alert = create(client, auth, status="ISSUED").json()["data"]
    assert alert["status"] == "ISSUED"
    assert alert["issued_at"] is not None
    assert {c["status"] for c in alert["channels"]} == {"NOTIFIED"}
    assert alert["delivery_summary"] == {
        "total": 2,
        "notified": 2,
        "failed": 0,
        "pending": 0,
        "all_delivered": True,
    }
    assert sorted(ch for _, ch in notifier.sent) == ["hospitals", "public_mobile"]


def test_draft_to_ready_to_issued_is_one_record(client, auth):
    alert_id = create(client, auth).json()["data"]["alert_id"]
    ready = client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "READY"}, headers=auth)
    assert ready.json()["data"]["status"] == "READY"
    issued = client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "ISSUED"}, headers=auth)
    data = issued.json()["data"]
    assert data["alert_id"] == alert_id
    assert data["status"] == "ISSUED"
    assert client.get("/api/v1/alerts").json()["data"]["total"] == 1


def test_a_draft_can_be_edited_before_issue(client, auth):
    alert_id = create(client, auth).json()["data"]["alert_id"]
    edited = client.patch(
        f"/api/v1/alerts/{alert_id}",
        json={"severity": "SEVERE_HEATWAVE", "channels": ["display_boards"]},
        headers=auth,
    ).json()["data"]
    assert edited["severity"] == "SEVERE_HEATWAVE"
    assert [c["channel"] for c in edited["channels"]] == ["display_boards"]


def test_an_issued_alert_is_immutable(client, auth):
    alert_id = create(client, auth, status="ISSUED").json()["data"]["alert_id"]
    for change in ({"message": "A different message entirely."}, {"status": "DRAFT"}):
        r = client.patch(f"/api/v1/alerts/{alert_id}", json=change, headers=auth)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CONFLICT"


def test_one_failed_channel_is_reported_not_swallowed(client, auth, notifier):
    notifier.failing["hospitals"] = DeliveryResult("FAILED", "gateway timeout")
    r = create(client, auth, status="ISSUED")
    assert r.status_code == 201  # the alert exists and is issued
    alert = r.json()["data"]
    by_channel = {c["channel"]: c for c in alert["channels"]}
    assert by_channel["public_mobile"]["status"] == "NOTIFIED"
    assert by_channel["hospitals"]["status"] == "FAILED"
    assert by_channel["hospitals"]["detail"] == "gateway timeout"
    assert alert["delivery_summary"]["failed"] == 1
    assert alert["delivery_summary"]["all_delivered"] is False
    stored = client.get(f"/api/v1/alerts/{alert['alert_id']}").json()["data"]
    assert stored["delivery_summary"]["failed"] == 1


def test_a_notifier_that_raises_marks_only_that_channel_failed(client, auth, notifier):
    notifier.failing["public_mobile"] = RuntimeError("boom with internal detail")
    alert = create(client, auth, status="ISSUED").json()["data"]
    by_channel = {c["channel"]: c for c in alert["channels"]}
    assert by_channel["public_mobile"]["status"] == "FAILED"
    assert "boom" not in str(by_channel["public_mobile"]["detail"])
    assert by_channel["hospitals"]["status"] == "NOTIFIED"


def test_replaying_a_request_id_returns_the_same_alert(client, auth, notifier):
    payload = body(status="ISSUED")
    first = client.post("/api/v1/alerts", json=payload, headers=auth)
    again = client.post("/api/v1/alerts", json=payload, headers=auth)
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["data"]["alert_id"] == first.json()["data"]["alert_id"]
    assert again.json()["data"]["idempotent_replay"] is True
    assert client.get("/api/v1/alerts").json()["data"]["total"] == 1
    assert len(notifier.sent) == 2  # not notified a second time


def test_a_reused_request_id_with_different_content_is_a_conflict(client, auth):
    payload = body()
    client.post("/api/v1/alerts", json=payload, headers=auth)
    r = client.post("/api/v1/alerts", json={**payload, "severity": "SEVERE_HEATWAVE"}, headers=auth)
    assert r.status_code == 409


def test_new_request_ids_create_separate_alerts(client, auth):
    create(client, auth)
    create(client, auth)
    assert client.get("/api/v1/alerts").json()["data"]["total"] == 2


def test_invalid_alerts_are_rejected(client, auth):
    assert create(client, auth, severity="NORMAL").status_code == 422
    assert create(client, auth, channels=[]).status_code == 422
    assert create(client, auth, message="short").status_code == 422
    assert create(client, auth, client_request_id="not-a-uuid").status_code == 422
    unknown_channel = create(client, auth, channels=["carrier_pigeon"])
    assert unknown_channel.status_code == 400
    assert "public_mobile" in unknown_channel.json()["error"]["details"]["valid"]
    assert create(client, auth, region_id="atlantis").status_code == 404
    assert create(client, auth, prediction_id="pred_missing").status_code == 400


def test_duplicate_channels_are_notified_once(client, auth, notifier):
    create(client, auth, channels=["hospitals", "hospitals"], status="ISSUED")
    assert [ch for _, ch in notifier.sent] == ["hospitals"]


def test_alert_can_reference_the_prediction_that_justified_it(client, auth):
    made = client.post("/api/v1/predict", json={"region_id": "mumbai"}).json()["data"]
    alert = create(client, auth, prediction_id=made["prediction_id"]).json()["data"]
    assert alert["prediction_id"] == made["prediction_id"]


def test_list_filters_and_paginates(client, auth):
    create(client, auth)
    create(client, auth, region_id="kurla", status="ISSUED")
    create(client, auth, region_id="kurla")
    listing = lambda **p: client.get("/api/v1/alerts", params=p).json()["data"]  # noqa: E731
    assert listing()["total"] == 3
    assert listing(status="ISSUED")["total"] == 1
    assert listing(region_id="kurla")["total"] == 2
    page = listing(limit=1, offset=1)
    assert (len(page["alerts"]), page["total"]) == (1, 3)
    assert client.get("/api/v1/alerts", params={"limit": 500}).status_code == 422
    assert client.get("/api/v1/alerts", params={"status": "SENT"}).status_code == 422


def test_unknown_alert_is_404(client):
    assert client.get("/api/v1/alerts/HW-2026-9999").status_code == 404


def test_alert_writes_are_rate_limited(client, auth):
    limit = client.app_ctx.settings.rate_limit_alerts_per_minute
    codes = [create(client, auth).status_code for _ in range(limit + 1)]
    assert codes[-1] == 429


def test_channel_list_matches_the_ui(client):
    labels = [c["label"] for c in client.get("/api/v1/alert-channels").json()["data"]]
    assert labels == [
        "Public Mobile Alert",
        "Government Portal",
        "Public Display Boards",
        "Emergency Services",
        "Hospitals & Health Centres",
    ]
