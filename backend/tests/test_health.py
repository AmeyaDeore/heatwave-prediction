from fastapi.testclient import TestClient

from heatwave_api.main import app


def test_health_returns_ok():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_reports_the_loaded_model(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "success"
    assert body["data"] | {"started_at": None} == {
        "status": "ready",
        "environment": "test",
        "model_version": "xgboost-test",
        "model_family": "xgboost",
        "explainer_id": "xgboost-test+shap.0000",
        "database": "ok",
        "notifications_mode": "mock",
        "started_at": None,
    }


def test_reference_data_for_the_frontend(client):
    data = client.get("/api/v1/reference").json()["data"]
    assert [r["id"] for r in data["regions"]] == ["mumbai", "kurla", "andheri", "dharavi", "colaba"]
    assert [c["code"] for c in data["risk_classes"]] == ["NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"]
    assert data["alert_statuses"] == ["DRAFT", "READY", "ISSUED"]
    assert {c["label"] for c in data["alert_channels"]} >= {"Hospitals & Health Centres"}
    assert data["features"]["temp_deviation_c"]["label"] == "Temperature Deviation"
    assert data["max_forecast_days"] == 3


def test_model_endpoint_serves_the_recorded_metrics(client):
    data = client.get("/api/v1/model").json()["data"]
    assert data["model_version"] == "xgboost-test"
    assert (data["precision"], data["recall"], data["f1"], data["confidence"]) == (
        0.85,
        0.91,
        0.88,
        0.97,
    )
