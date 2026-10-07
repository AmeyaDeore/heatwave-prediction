import pytest

from heatwave_api import errors
from heatwave_api.errors import ApiError


def test_success_envelope_has_status_data_and_meta(client):
    body = client.get("/api/v1/regions").json()
    assert body["status"] == "ok"
    assert {r["id"] for r in body["data"]} >= {"mumbai", "kurla", "andheri", "dharavi", "colaba"}
    assert body["meta"]["api_version"] == "v1"
    assert body["meta"]["request_id"]


def test_request_id_is_echoed_in_header_and_body(client):
    r = client.get("/api/v1/regions", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    assert r.json()["meta"]["request_id"] == "abc-123"


def test_unknown_route_uses_the_error_envelope(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["kind"] == "client"
    assert body["meta"]["request_id"]


def test_wrong_method_is_a_405_envelope(client):
    r = client.delete("/api/v1/regions")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_validation_error_names_the_field_and_never_echoes_input(client):
    r = client.post("/api/v1/predict", json={"region_id": "MUMBAI; DROP TABLE", "lead_days": 1})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "region_id"
    assert "DROP TABLE" not in r.text


def test_unknown_request_fields_are_rejected_not_ignored(client):
    r = client.post("/api/v1/predict", json={"region_id": "mumbai", "lead_dayz": 2})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "lead_dayz"


def test_unexpected_exception_is_a_500_without_a_stack_trace(client, predictor):
    predictor.fail = RuntimeError("secret internal path C:/models/x.pkl")
    r = client.post("/api/v1/predict", json={"region_id": "mumbai"})
    assert r.status_code == 500
    error = r.json()["error"]
    assert error["kind"] == "internal"
    assert "secret internal path" not in r.text
    assert "Traceback" not in r.text
    assert r.json()["meta"]["request_id"] in error["message"]


@pytest.mark.parametrize(
    ("name", "status", "kind"),
    [
        ("BadRequest", 400, "client"),
        ("Unauthorized", 401, "client"),
        ("NotFound", 404, "client"),
        ("Conflict", 409, "client"),
        ("TooManyRequests", 429, "client"),
        ("UpstreamUnavailable", 503, "upstream"),
        ("ModelUnavailable", 503, "internal"),
        ("PredictionFailed", 500, "internal"),
    ],
)
def test_error_taxonomy_maps_kind_to_status(name, status, kind):
    cls = getattr(errors, name)
    assert issubclass(cls, ApiError)
    assert (cls.status_code, cls.kind) == (status, kind)
