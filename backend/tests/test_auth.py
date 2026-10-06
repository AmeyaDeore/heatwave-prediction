"""Login, tokens, logout, and the read-access switch."""

import pytest
from api_support import PASSWORD

from heatwave_api.errors import Unauthenticated
from heatwave_api.security import TokenService, hash_password, verify_password

LOGIN = "/api/v1/auth/login"


def test_password_hashing():
    stored = hash_password("s3cret-passphrase")
    assert stored.startswith("scrypt$") and "s3cret" not in stored
    assert verify_password("s3cret-passphrase", stored)
    assert not verify_password("s3cret-passphrase!", stored)
    assert stored != hash_password("s3cret-passphrase")  # salted
    assert not verify_password("x", "not-a-hash")


def test_tokens_are_signed_and_expire():
    clock = [1_000_000.0]
    tokens = TokenService("k" * 40, ttl_minutes=60, clock=lambda: clock[0])
    token, expires_at, jti = tokens.issue({"id": 7, "username": "a", "role": "AUTHORITY"})
    claims = tokens.decode(token)
    assert (claims["sub"], claims["jti"]) == ("7", jti)
    assert expires_at.timestamp() == 1_000_000 + 3600

    header, payload, signature = token.split(".")
    forged = TokenService("other-key" * 5, 60, clock=lambda: clock[0]).issue(
        {"id": 1, "username": "x", "role": "AUTHORITY"}
    )[0]
    for bad in (f"{header}.{forged.split('.')[1]}.{signature}", token + "x", "a.b", ""):
        with pytest.raises(Unauthenticated) as err:
            tokens.decode(bad)
        assert err.value.code == "INVALID_TOKEN"

    clock[0] += 3600
    with pytest.raises(Unauthenticated) as err:
        tokens.decode(token)
    assert err.value.code == "TOKEN_EXPIRED"


def test_login_me_logout(client, user):
    response = client.post(LOGIN, json={"username": "officer", "password": PASSWORD})
    assert response.status_code == 200
    session = response.json()["data"]
    assert session["token_type"] == "bearer" and session["expires_at"]
    assert session["user"] == {
        "id": user["id"],
        "username": "officer",
        "display_name": "Duty Officer",
        "role": "AUTHORITY",
    }
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["data"]["username"] == "officer"

    assert client.post("/api/v1/auth/logout", headers=headers).json()["data"] == {
        "signed_out": True
    }
    after = client.get("/api/v1/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "TOKEN_REVOKED"


@pytest.mark.parametrize(
    "username, password", [("officer", "wrong password"), ("nobody", PASSWORD)]
)
def test_failed_login_does_not_reveal_which_part_was_wrong(client, user, username, password):
    response = client.post(LOGIN, json={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "category": "auth",
        "message": "Invalid username or password.",
        "details": None,
    }


def test_validation_errors_never_echo_the_password(client):
    response = client.post(LOGIN, json={"username": "", "password": "hunter2-secret"})
    assert response.status_code == 422
    assert "hunter2" not in response.text


def test_a_deactivated_user_is_signed_out(client, user, repo, auth):
    repo.conn.execute("UPDATE users SET active = 0 WHERE id = ?", (user["id"],))
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401
    response = client.post(LOGIN, json={"username": "officer", "password": PASSWORD})
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_is_rate_limited(make_client, user):
    client = make_client(rate_limit_login="3/minute")
    guess = {"username": "officer", "password": "guess"}  # pragma: allowlist secret
    codes = [client.post(LOGIN, json=guess).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_reads_can_be_closed_to_anonymous_users(make_client, user):
    client = make_client(auth_required_for_reads=True)
    for path in ("/api/v1/weather", "/api/v1/alerts", "/api/v1/analytics", "/api/v1/reference"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/v1/predict", json={"region_id": "mumbai"}).status_code == 401
    token = client.post(LOGIN, json={"username": "officer", "password": PASSWORD}).json()
    headers = {"Authorization": f"Bearer {token['data']['access_token']}"}
    assert client.get("/api/v1/alerts", headers=headers).status_code == 200
    assert client.get("/api/v1/health").status_code == 200  # readiness stays open
