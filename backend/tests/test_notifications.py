"""Part 09: templates, recipients, providers, retry policy, audit trail and dispatch."""

import io
import sqlite3
import threading
import urllib.error
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fakes import FakePredictor, FakeWeather
from fastapi.testclient import TestClient

from heatwave_api.app import create_app
from heatwave_api.catalog import Catalog
from heatwave_api.config import Settings
from heatwave_api.notifications import providers as prov
from heatwave_api.notifications.providers import MockProvider, PermanentError, TransientError
from heatwave_api.notifications.recipients import Recipients
from heatwave_api.notifications.service import (
    ConfigurationError,
    NotificationService,
    RetryPolicy,
    build_providers,
)
from heatwave_api.notifications.templates import Message, Templates
from heatwave_api.notifier import DeliveryResult
from heatwave_api.repositories import MemoryRepository
from heatwave_api.schemas import AlertOut, ChannelDelivery, DeliverySummary, RegionOut

ALL_CHANNELS = [
    "public_mobile",
    "government_portal",
    "display_boards",
    "emergency_services",
    "hospitals",
]
LONG = (
    "Severe heatwave conditions are expected across the city for the next three days. "
    "Avoid prolonged outdoor exposure between noon and 4 PM, stay hydrated, check on "
    "elderly neighbours and seek shade or cooling centres if you feel unwell."
)


def make_alert(message="Stay hydrated and avoid the midday sun.", severity="SEVERE_HEATWAVE"):
    now = datetime(2026, 5, 10, 6, 30, tzinfo=UTC)
    region = RegionOut(
        id="mumbai",
        name="Mumbai",
        district="Mumbai City",
        state="Maharashtra",
        zone="Konkan",
        lat=19.07,
        lon=72.87,
    )
    return AlertOut(
        alert_id="HW-2026-0007",
        status="ISSUED",
        severity=severity,
        region=region,
        message=message,
        prediction_id=None,
        channels=[],
        delivery_summary=DeliverySummary(
            total=0, notified=0, failed=0, pending=0, all_delivered=True
        ),
        created_at=now,
        created_by="user_demo",
        issued_at=now,
        updated_at=now,
    )


@pytest.fixture
def settings():
    return Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None)


@pytest.fixture
def catalog(settings):
    return Catalog.load(settings)


@pytest.fixture
def templates(settings):
    return Templates.load(settings.notification_templates_file)


def mechanisms(catalog):
    return {c.id: c.mechanism for c in catalog.channels.values()}


class Scripted:
    """A provider that plays back a script of outcomes, one per call."""

    name = "scripted"

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def send(self, recipient, message):
        self.calls.append(recipient)
        step = self.script.pop(0) if self.script else "ok"
        if isinstance(step, Exception):
            raise step
        return f"ref-{len(self.calls)}"


def service(catalog, templates, store, sms=None, email=None, recipients=None, sleeps=None):
    spec = recipients or {
        "channels": {
            "public_mobile": {"default": ["+15005550006"]},
            "emergency_services": {"default": ["+15005550006"]},
            "hospitals": {"regions": {"mumbai": ["a@example.invalid", "b@example.invalid"]}},
        }
    }
    return NotificationService(
        catalog,
        templates,
        Recipients(spec, mechanisms(catalog)),
        {"sms": sms or MockProvider("sms"), "email": email or MockProvider("email")},
        store,
        RetryPolicy(max_attempts=3, backoff_seconds=2.0),
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
    )


# -- channel mapping ------------------------------------------------------------------


def test_every_ui_channel_maps_to_a_delivery_mechanism(catalog):
    assert mechanisms(catalog) == {
        "public_mobile": "sms",
        "government_portal": "in_app",
        "display_boards": "in_app",
        "emergency_services": "sms",
        "hospitals": "email",
    }


def test_an_unknown_mechanism_stops_startup(tmp_path, settings):
    bad = tmp_path / "channels.yaml"
    bad.write_text("channels:\n  - {id: fax, label: Fax, mechanism: fax}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mechanism 'fax'"):
        Catalog.load(settings.model_copy(update={"alert_channels_file": bad}))


# -- templates ------------------------------------------------------------------------


def test_email_and_in_app_follow_the_mockup_style(templates):
    email = templates.render("email", make_alert())
    assert email.subject == "SEVERE HEATWAVE ALERT - Mumbai (HW-2026-0007)"
    assert "Stay hydrated and avoid the midday sun." in email.body
    assert "10 May 2026, 12:00 IST" in email.body  # 06:30 UTC shown in IST
    in_app = templates.render("in_app", make_alert())
    assert (in_app.subject, in_app.body) == (
        "SEVERE HEATWAVE ALERT - Mumbai",
        "Stay hydrated and avoid the midday sun.",
    )


def test_short_sms_is_sent_whole(templates):
    sms = templates.render("sms", make_alert()).body
    assert sms == (
        "SEVERE HEATWAVE ALERT - Mumbai: Stay hydrated and avoid the midday sun. Ref HW-2026-0007"
    )


def test_long_sms_shortens_only_the_advisory_text(templates):
    sms = templates.render("sms", make_alert(LONG)).body
    assert len(sms) <= templates.sms_max_chars == 160
    assert sms.startswith("SEVERE HEATWAVE ALERT - Mumbai: Severe heatwave")
    assert sms.endswith("... Ref HW-2026-0007")  # reference survives the cut
    assert sms.isascii()  # GSM-7 safe: one 160-character segment
    cut_word = sms.split("...")[0].split()[-1]
    assert cut_word in LONG.split() or cut_word.rstrip(",.") in LONG  # cut at a word boundary


def test_a_template_placeholder_typo_fails_at_load(settings):
    import yaml

    spec = yaml.safe_load(settings.notification_templates_file.read_text(encoding="utf-8"))
    spec["sms"]["body"] = "${severity_label} ${regoin_name}"
    with pytest.raises(KeyError):
        Templates(spec)


# -- recipients -----------------------------------------------------------------------


def test_region_list_overrides_the_default_and_duplicates_collapse(catalog):
    r = Recipients(
        {
            "channels": {
                "hospitals": {
                    "default": ["d@example.invalid"],
                    "regions": {"kurla": ["k@example.invalid", "k@example.invalid"]},
                }
            }
        },
        mechanisms(catalog),
    )
    assert r.resolve("hospitals", "kurla") == ["k@example.invalid"]
    assert r.resolve("hospitals", "colaba") == ["d@example.invalid"]
    assert r.resolve("public_mobile", "kurla") == []


@pytest.mark.parametrize(
    "spec, error",
    [
        ({"public_mobile": {"default": ["9876543210"]}}, "invalid sms"),
        ({"hospitals": {"default": ["not-an-email"]}}, "invalid email"),
        ({"display_boards": {"default": ["x@example.invalid"]}}, "in_app"),
        ({"carrier_pigeon": {"default": []}}, "unknown channel"),
    ],
)
def test_bad_recipient_config_stops_startup(catalog, spec, error):
    with pytest.raises(ValueError, match=error):
        Recipients({"channels": spec}, mechanisms(catalog))


def test_the_committed_development_list_cannot_reach_real_people(settings, catalog):
    import yaml

    spec = yaml.safe_load(settings.notification_recipients_file.read_text(encoding="utf-8"))
    Recipients(spec, mechanisms(catalog))  # valid
    for entry in spec["channels"].values():
        for group in [entry.get("default", []), *entry.get("regions", {}).values()]:
            for r in group:
                assert r.endswith(".invalid") or r.startswith("+1500555"), r


# -- dispatch, retry, audit -----------------------------------------------------------


def test_sms_and_email_deliver_to_every_recipient_and_are_audited(catalog, templates):
    store, email = MemoryRepository(), MockProvider("email")
    svc = service(catalog, templates, store, email=email)
    result = svc.send(make_alert(), "hospitals")
    assert result == DeliveryResult("NOTIFIED", "sent to 2 recipients via mock-email")
    assert [r for r, _ in email.outbox] == ["a@example.invalid", "b@example.invalid"]
    assert email.outbox[0][1].subject.startswith("SEVERE HEATWAVE ALERT")
    attempts = store.list_attempts("HW-2026-0007")
    assert [(a.recipient, a.attempt, a.outcome) for a in attempts] == [
        ("a@example.invalid", 1, "SUCCESS"),
        ("b@example.invalid", 1, "SUCCESS"),
    ]
    assert attempts[0].provider_ref == "mock-email-1"


def test_transient_failures_are_retried_with_backoff(catalog, templates):
    store, sleeps = MemoryRepository(), []
    sms = Scripted(TransientError("HTTP 503"), TransientError("HTTP 503"), "ok")
    result = service(catalog, templates, store, sms=sms, sleeps=sleeps).send(
        make_alert(), "public_mobile"
    )
    assert result.status == "NOTIFIED"
    assert sleeps == [2.0, 4.0]  # doubling backoff
    outcomes = [a.outcome for a in store.list_attempts("HW-2026-0007")]
    assert outcomes == ["TRANSIENT_FAILURE", "TRANSIENT_FAILURE", "SUCCESS"]


def test_transient_failures_give_up_after_max_attempts(catalog, templates):
    store, sleeps = MemoryRepository(), []
    sms = Scripted(*[TransientError("provider did not answer within 10s")] * 5)
    result = service(catalog, templates, store, sms=sms, sleeps=sleeps).send(
        make_alert(), "public_mobile"
    )
    assert result.status == "FAILED"
    assert "gave up after 3 attempts" in result.detail
    assert len(sms.calls) == 3 and sleeps == [2.0, 4.0]


def test_a_permanent_failure_is_not_retried(catalog, templates):
    store, sleeps = MemoryRepository(), []
    sms = Scripted(PermanentError("provider rejected the message (HTTP 400): invalid To"))
    result = service(catalog, templates, store, sms=sms, sleeps=sleeps).send(
        make_alert(), "emergency_services"
    )
    assert result.status == "FAILED"
    assert "invalid To" in result.detail
    assert len(sms.calls) == 1 and sleeps == []
    assert [a.outcome for a in store.list_attempts("HW-2026-0007")] == ["PERMANENT_FAILURE"]


def test_an_unexpected_provider_error_is_retried_but_not_leaked(catalog, templates):
    store = MemoryRepository()
    sms = Scripted(*[RuntimeError("secret internals")] * 3)
    result = service(catalog, templates, store, sms=sms).send(make_alert(), "public_mobile")
    assert result.status == "FAILED"
    assert "secret" not in result.detail
    assert len(sms.calls) == 3


def test_one_failed_recipient_fails_the_channel_and_says_how_many(catalog, templates):
    email = Scripted("ok", PermanentError("mailbox does not exist"))
    result = service(catalog, templates, MemoryRepository(), email=email).send(
        make_alert(), "hospitals"
    )
    assert result.status == "FAILED"
    assert result.detail.startswith("1 of 2 email recipients failed: mailbox does not exist")


def test_no_recipients_is_a_recorded_failure_not_a_silent_skip(catalog, templates):
    store = MemoryRepository()
    svc = service(catalog, templates, store, recipients={"channels": {}})
    result = svc.send(make_alert(), "public_mobile")
    assert result == DeliveryResult("FAILED", "no sms recipients configured for mumbai")
    [attempt] = store.list_attempts("HW-2026-0007")
    assert (attempt.provider, attempt.outcome) == ("none", "PERMANENT_FAILURE")


def test_in_app_publishes_one_advisory_without_any_provider(catalog, templates):
    store = MemoryRepository()
    sms, email = Scripted(), Scripted()
    svc = service(catalog, templates, store, sms=sms, email=email)
    for _ in range(2):  # a resumed job must not publish twice
        assert svc.send(make_alert(), "display_boards").status == "NOTIFIED"
    [advisory] = store.list_advisories(region_id="mumbai", since=None, limit=10)
    assert advisory.title == "SEVERE HEATWAVE ALERT - Mumbai"
    assert sms.calls == email.calls == []


# -- providers ------------------------------------------------------------------------


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b'{"message":"no"}'))


@pytest.mark.parametrize(
    "raised, expected",
    [
        (http_error(503), TransientError),
        (http_error(429), TransientError),
        (http_error(400), PermanentError),
        (http_error(401), PermanentError),
        (TimeoutError(), TransientError),
        (urllib.error.URLError("dns failure"), TransientError),
    ],
)
def test_http_failures_are_classified_for_retry(monkeypatch, raised, expected):
    def urlopen(request, timeout):
        assert timeout == 7.0
        raise raised

    monkeypatch.setattr(prov.urllib.request, "urlopen", urlopen)
    sms = prov.TwilioSms("AC123", "token", "+15005550006", timeout=7.0)
    with pytest.raises(expected):
        sms.send("+15005550006", Message("hello"))


def test_twilio_and_sendgrid_build_the_right_requests(monkeypatch):
    seen = []

    class Response(io.BytesIO):
        status, headers = 201, {"X-Message-Id": "sg-123"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        seen.append(request)
        return Response(b'{"sid": "SM123"}')

    monkeypatch.setattr(prov.urllib.request, "urlopen", urlopen)
    assert (
        prov.TwilioSms("AC1", "tok", "+15005550006", 5).send("+911234567", Message("hi")) == "SM123"
    )
    assert (
        prov.SendGridEmail("key", "from@x.org", 5).send("to@x.org", Message("b", "s")) == "sg-123"
    )
    twilio, sendgrid = seen
    assert twilio.full_url.endswith("/Accounts/AC1/Messages.json")
    assert b"To=%2B911234567" in twilio.data and twilio.get_header("Authorization").startswith(
        "Basic "
    )
    assert sendgrid.get_header("Authorization") == "Bearer key"
    assert b'"subject": "s"' in sendgrid.data


def test_mock_mode_never_builds_a_real_provider(settings):
    built = build_providers(settings)
    assert {p.name for p in built.values()} == {"mock-sms", "mock-email"}


def test_live_mode_needs_every_credential_and_is_refused_in_test(settings):
    with pytest.raises(ConfigurationError, match="APP_ENV=test"):
        build_providers(settings.model_copy(update={"notifications_mode": "live"}))
    local = settings.model_copy(update={"notifications_mode": "live", "app_env": "local"})
    with pytest.raises(ConfigurationError, match="EMAIL_API_KEY"):
        build_providers(local)


# -- end to end through the API (real NotificationService, mock providers) ----------------


def login(client, settings):
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "official", "password": settings.demo_user_password.get_secret_value()},
    )
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture
def real_client(settings):
    app = create_app(settings, predictor=FakePredictor(), weather=FakeWeather())
    with TestClient(app) as c:
        c.app_ctx = app.state.ctx
        c.bearer = login(c, settings)
        yield c


def issue(client, channels=ALL_CHANNELS, region_id="mumbai", message=LONG):
    r = client.post(
        "/api/v1/alerts",
        json={
            "client_request_id": str(uuid4()),
            "region_id": region_id,
            "severity": "SEVERE_HEATWAVE",
            "message": message,
            "channels": channels,
            "status": "ISSUED",
        },
        headers=client.bearer,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_background_dispatch_returns_pending_then_settles(real_client):
    alert = issue(real_client)
    assert {c["status"] for c in alert["channels"]} <= {"PENDING", "NOTIFIED"}
    real_client.app_ctx.alerts.dispatcher.join()
    stored = real_client.get(f"/api/v1/alerts/{alert['alert_id']}").json()["data"]
    assert {c["status"] for c in stored["channels"]} == {"NOTIFIED"}
    assert stored["delivery_summary"]["all_delivered"] is True
    assert stored["updated_at"] > alert["issued_at"]  # pollers can see it moved


def test_issued_alert_is_delivered_published_and_audited(real_client):
    alert = issue(real_client)
    real_client.app_ctx.alerts.dispatcher.join()
    advisories = real_client.get("/api/v1/advisories", params={"region_id": "mumbai"}).json()
    assert sorted(a["channel"] for a in advisories["data"]) == [
        "display_boards",
        "government_portal",
    ]
    path = f"/api/v1/alerts/{alert['alert_id']}/attempts"
    assert real_client.get(path).status_code == 401  # recipients are not public
    attempts = real_client.get(path, headers=real_client.bearer).json()["data"]
    by_channel = {}
    for a in attempts:
        by_channel.setdefault(a["channel"], []).append(a)
    assert set(by_channel) == set(ALL_CHANNELS)
    assert [a["recipient"] for a in by_channel["hospitals"]] == [
        "kem-hospital@example.invalid",
        "bmc-health@example.invalid",
    ]
    assert all(a["outcome"] == "SUCCESS" for a in attempts)
    assert (
        real_client.get(
            "/api/v1/alerts/HW-2026-9999/attempts", headers=real_client.bearer
        ).status_code
        == 404
    )


def test_a_slow_channel_does_not_hold_up_the_response(settings):
    gate = threading.Event()

    class Slow:
        def send(self, alert, channel_id):
            gate.wait(5)
            return DeliveryResult("NOTIFIED")

    app = create_app(settings, predictor=FakePredictor(), weather=FakeWeather(), notifier=Slow())
    with TestClient(app) as c:
        c.bearer = login(c, settings)
        alert = issue(c, channels=["hospitals"])
        assert alert["channels"][0]["status"] == "PENDING"
        assert alert["delivery_summary"]["pending"] == 1
        gate.set()
        app.state.ctx.alerts.dispatcher.join()
        assert (
            c.get(f"/api/v1/alerts/{alert['alert_id']}").json()["data"]["channels"][0]["status"]
            == "NOTIFIED"
        )


def test_pending_channels_are_resumed_at_startup(tmp_path, settings):
    """A crash after ISSUED was stored but before delivery: the next start sends it."""
    file_settings = settings.model_copy(
        update={"database_url": f"sqlite:///{(tmp_path / 'hw.db').as_posix()}"}
    )
    first = create_app(file_settings, predictor=FakePredictor(), weather=FakeWeather())
    with TestClient(first) as c:
        c.bearer = login(c, settings)
        draft = c.post(
            "/api/v1/alerts",
            json={
                "client_request_id": str(uuid4()),
                "region_id": "kurla",
                "severity": "HEATWAVE",
                "message": "Heatwave conditions expected tomorrow afternoon.",
                "channels": ["hospitals", "display_boards"],
            },
            headers=c.bearer,
        ).json()["data"]
    # The state a crash between "stored ISSUED + PENDING" and "delivered" leaves behind.
    with sqlite3.connect(tmp_path / "hw.db") as db:
        db.execute(
            "UPDATE alerts SET status = 'ISSUED', issued_at = updated_at WHERE alert_id = ?",
            (draft["alert_id"],),
        )
        db.execute("UPDATE alert_channel_deliveries SET status = 'PENDING'")

    restarted = create_app(file_settings, predictor=FakePredictor(), weather=FakeWeather())
    with TestClient(restarted) as c:
        restarted.state.ctx.alerts.dispatcher.join()
        alert = c.get(f"/api/v1/alerts/{draft['alert_id']}").json()["data"]
        assert {ch["status"] for ch in alert["channels"]} == {"NOTIFIED"}
        assert restarted.state.ctx.repo.alerts_with_pending_deliveries() == []


def test_attempts_are_append_only(real_client):
    issue(real_client, channels=["hospitals"])
    real_client.app_ctx.alerts.dispatcher.join()
    conn = real_client.app_ctx.repo.db.conn
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE notification_attempts SET outcome = 'SUCCESS'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM notification_attempts")


def test_alert_channel_list_exposes_the_mechanism(real_client):
    channels = real_client.get("/api/v1/alert-channels").json()["data"]
    assert {c["id"]: c["mechanism"] for c in channels}["hospitals"] == "email"


def test_update_delivery_for_a_missing_row_is_an_error(real_client):
    with pytest.raises(LookupError):
        real_client.app_ctx.repo.update_delivery(
            "HW-2026-9999",
            ChannelDelivery(
                channel="hospitals", label="x", status="FAILED", updated_at=datetime.now(UTC)
            ),
        )
