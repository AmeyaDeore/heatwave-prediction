"""Revision 2, Part 07 §A: the ML-service role, the batch endpoint and model metadata.

Role `ml` is what the Node.js API calls: prediction + SHAP, weather, regions, model metadata
and readiness, with no database, users, alerts or CORS, and a service token when one is set.
Role `app` (the default) must keep behaving exactly as in Parts 07-09; the rest of the suite
covers that, and the batch tests below also run in role `app`.
"""

import pytest
from fakes import FakePredictor, FakeWeather
from fastapi.testclient import TestClient

from heatwave_api.app import check_startup, create_app
from heatwave_api.catalog import Catalog
from heatwave_api.config import Settings
from heatwave_api.schemas import MAX_BATCH_ITEMS

TOKEN = "t" * 40  # pragma: allowlist secret


def ml_settings(**kw) -> Settings:
    return Settings(app_env="test", service_role="ml", _env_file=None, **kw)


@pytest.fixture
def predictor():
    return FakePredictor()


@pytest.fixture
def weather():
    return FakeWeather()


@pytest.fixture
def ml(predictor, weather):
    app = create_app(ml_settings(), predictor=predictor, weather=weather)
    with TestClient(app, raise_server_exceptions=False) as c:
        c.app_ctx = app.state.ctx
        yield c


def batch(*pairs):
    return {"items": [{"region_id": r, "lead_days": lead} for r, lead in pairs]}


# -- what role ml serves -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/health", None),
        ("get", "/api/v1/health/ready", None),
        ("get", "/api/v1/regions", None),
        ("get", "/api/v1/weather", None),
        ("get", "/api/v1/model", None),
        ("post", "/api/v1/predict", {"region_id": "mumbai"}),
        ("post", "/api/v1/predict/batch", batch(("mumbai", 0))),
    ],
)
def test_role_ml_serves_the_ml_endpoints(ml, method, path, body):
    r = getattr(ml, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 200, r.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/alerts"),
        ("post", "/api/v1/alerts"),
        ("get", "/api/v1/alert-channels"),
        ("get", "/api/v1/advisories"),
        ("get", "/api/v1/analytics"),
        ("get", "/api/v1/predictions/latest?region_id=mumbai"),
        ("post", "/api/v1/auth/login"),
        ("get", "/api/v1/auth/me"),
    ],
)
def test_role_ml_does_not_mount_application_endpoints(ml, method, path):
    r = getattr(ml, method)(path)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_role_ml_has_no_database_users_alerts_or_limiter(ml):
    c = ml.app_ctx
    assert (c.repo, c.users, c.tokens, c.notifier, c.alerts, c.limiter) == (None,) * 6
    assert ml.get("/api/v1/health/ready").json()["data"]["ready"] is True


def test_role_ml_answers_no_cors_preflight(ml):
    r = ml.options(
        "/api/v1/predict",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in r.headers


def test_role_ml_is_not_rate_limited(predictor, weather):
    """The Node.js API applies the public limits; the internal service must not throttle it."""
    app = create_app(
        ml_settings(rate_limit_predict_per_minute=2), predictor=predictor, weather=weather
    )
    with TestClient(app) as c:
        codes = {
            c.post("/api/v1/predict", json={"region_id": "mumbai"}).status_code for _ in range(5)
        }
    assert codes == {200}


def test_role_ml_readiness_still_reports_missing_weather(ml, weather):
    weather.fail = True
    r = ml.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["data"]["weather_data"] == "unavailable"


# -- service token --------------------------------------------------------------------


@pytest.fixture
def ml_with_token(predictor, weather):
    app = create_app(ml_settings(ml_service_token=TOKEN), predictor=predictor, weather=weather)
    with TestClient(app) as c:
        yield c


def test_a_configured_token_is_required(ml_with_token):
    for headers in ({}, {"X-Service-Token": "wrong"}):
        r = ml_with_token.post("/api/v1/predict", json={"region_id": "mumbai"}, headers=headers)
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "UNAUTHORIZED"
        assert body["meta"]["request_id"] == r.headers["x-request-id"]
    ok = ml_with_token.post(
        "/api/v1/predict", json={"region_id": "mumbai"}, headers={"X-Service-Token": TOKEN}
    )
    assert ok.status_code == 200


def test_liveness_needs_no_token(ml_with_token):
    assert ml_with_token.get("/health").status_code == 200


def test_the_local_placeholder_token_means_no_check(ml):
    assert ml.post("/api/v1/predict", json={"region_id": "mumbai"}).status_code == 200


@pytest.mark.parametrize("token", ["change-me-local-only", "too-short"])
@pytest.mark.parametrize("env", ["staging", "production"])
def test_role_ml_refuses_a_weak_token_outside_local_and_test(env, token):
    settings = Settings(app_env=env, service_role="ml", ml_service_token=token, _env_file=None)
    with pytest.raises(RuntimeError, match="ML_SERVICE_TOKEN"):
        check_startup(settings, Catalog.load(settings))


def test_role_ml_accepts_a_real_token_in_production():
    settings = Settings(
        app_env="production", service_role="ml", ml_service_token=TOKEN, _env_file=None
    )
    check_startup(settings, Catalog.load(settings))  # does not raise; AUTH_SECRET_KEY irrelevant


# -- POST /predict/batch (both roles) -------------------------------------------------


def test_batch_returns_predictions_in_request_order_from_one_model_call(ml, predictor):
    pairs = [("colaba", 3), ("mumbai", 0), ("kurla", 1)]
    r = ml.post("/api/v1/predict/batch", json=batch(*pairs))
    assert r.status_code == 200
    data = r.json()["data"]
    assert [(p["region"]["id"], p["forecast_window"]["lead_days"]) for p in data] == pairs
    assert predictor.batch_calls == 1
    # FakeWeather: tmax = 41 + lead, so lead 3 is 44 °C → HEATWAVE (≥ 40)
    assert {p["risk_class"] for p in data} == {"HEATWAVE"}
    assert len({p["prediction_id"] for p in data}) == 3


def test_batch_items_match_single_predictions(ml):
    single = ml.post("/api/v1/predict", json={"region_id": "andheri", "lead_days": 2}).json()[
        "data"
    ]
    (batched,) = ml.post("/api/v1/predict/batch", json=batch(("andheri", 2))).json()["data"]
    for key in (
        "risk_class",
        "confidence",
        "probabilities",
        "inputs",
        "explanation",
        "recommended_actions",
    ):
        assert batched[key] == single[key]


def test_batch_with_an_unknown_region_fails_before_scoring(ml, predictor):
    r = ml.post("/api/v1/predict/batch", json=batch(("mumbai", 0), ("atlantis", 0)))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "UNKNOWN_REGION"
    assert predictor.batch_calls == 0


def test_batch_with_missing_weather_fails_whole_and_scores_nothing(ml, predictor, weather):
    del weather.rows[("kurla", 2)]
    r = ml.post("/api/v1/predict/batch", json=batch(("mumbai", 0), ("kurla", 2)))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "WEATHER_DATA_UNAVAILABLE"
    assert predictor.batch_calls == 0


@pytest.mark.parametrize(
    "body",
    [
        {"items": []},
        batch(*[("mumbai", 0)] * (MAX_BATCH_ITEMS + 1)),
        batch(("mumbai", 4)),
        {"items": [{"region_id": "mumbai", "lead_dayz": 1}]},
        {"items": [{"region_id": "mumbai"}], "extra": True},
    ],
)
def test_batch_validation(ml, body):
    r = ml.post("/api/v1/predict/batch", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_batch_in_role_app_stores_every_prediction(client):
    data = client.post("/api/v1/predict/batch", json=batch(("dharavi", 0), ("dharavi", 1))).json()[
        "data"
    ]
    for p in data:
        lead = p["forecast_window"]["lead_days"]
        latest = client.get(f"/api/v1/predictions/latest?region_id=dharavi&lead_days={lead}")
        assert latest.json()["data"]["prediction_id"] == p["prediction_id"]


def test_batch_counts_once_against_the_predict_rate_limit(client):
    limit = client.app_ctx.settings.rate_limit_predict_per_minute
    big = batch(*[("mumbai", 0)] * 10)
    codes = [client.post("/api/v1/predict/batch", json=big).status_code for _ in range(limit + 1)]
    assert codes[:limit] == [200] * limit
    assert codes[-1] == 429


# -- GET /model and region fields -----------------------------------------------------


@pytest.mark.parametrize("role_client", ["ml", "client"])
def test_model_metadata_comes_from_the_loaded_model(request, role_client):
    c = request.getfixturevalue(role_client)
    data = c.get("/api/v1/model").json()["data"]
    assert data["model_version"] == "fake-model-v1"
    assert data["explainer_id"] == "fake-model-v1+shap.test"
    assert data["f1_macro"] == 0.82
    assert "support" not in data["per_class"]["NORMAL"]


def test_regions_expose_the_revision_2_fields(ml):
    regions = {r["id"]: r for r in ml.get("/api/v1/regions").json()["data"]}
    assert (regions["mumbai"]["kind"], regions["mumbai"]["parent"]) == ("city", None)
    assert (regions["kurla"]["kind"], regions["kurla"]["parent"]) == ("area", "mumbai")
    assert all(r["division"] for r in regions.values())
    assert all(regions[r["parent"]]["kind"] == "city" for r in regions.values() if r["parent"])


def test_catalog_applies_the_same_hierarchy_rule_as_ingestion(tmp_path):
    path = tmp_path / "regions.yaml"
    path.write_text(
        "regions:\n  - {id: kurla, name: Kurla, district: D, state: S, zone: coastal, "
        "lat: 19.0, lon: 72.8, kind: area}\n",
        encoding="utf-8",
    )
    settings = Settings(app_env="test", monitored_regions_file=path, _env_file=None)
    with pytest.raises(ValueError, match="parent"):
        Catalog.load(settings)


# -- GET /weather for every region at a lead (fix, Revision 2 step 4) -----------------


@pytest.mark.parametrize("lead", [0, 1, 3])
def test_all_regions_weather_honours_lead_days(ml, lead):
    data = ml.get(f"/api/v1/weather?lead_days={lead}").json()["data"]
    assert {r["lead_days"] for r in data} == {lead}
    assert {r["region"]["id"] for r in data} == {"mumbai", "kurla", "andheri", "dharavi", "colaba"}
    assert {r["tmax_c"] for r in data} == {41.0 + lead}  # FakeWeather: tmax = 41 + lead


def test_all_regions_weather_skips_regions_without_that_lead(ml, weather):
    del weather.rows[("kurla", 2)]
    data = ml.get("/api/v1/weather?lead_days=2").json()["data"]
    assert "kurla" not in {r["region"]["id"] for r in data} and len(data) == 4


def test_all_regions_weather_with_no_row_for_the_lead_is_unavailable(ml, weather):
    for rid in ("mumbai", "kurla", "andheri", "dharavi", "colaba"):
        del weather.rows[(rid, 3)]
    r = ml.get("/api/v1/weather?lead_days=3")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "WEATHER_DATA_UNAVAILABLE"
