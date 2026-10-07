"""Login and bearer-token gate (Part 07 §3.6; Part 15 owns and extends this).

What exists now: scrypt password hashes, HMAC-signed tokens with an expiry, a `UserStore`
seam, and the `current_user` dependency that protects write endpoints. What Part 15 adds:
users in the database (Part 08), roles/region scoping, and any refresh or revocation.
Until then the only user is a demo official seeded when APP_ENV is local or test.
"""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import Request

from heatwave_api.errors import Unauthorized
from heatwave_api.schemas import UserOut

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


@dataclass(frozen=True)
class User:
    id: str
    username: str
    display_name: str
    role: str
    password_hash: str

    def public(self) -> UserOut:
        return UserOut(
            id=self.id, username=self.username, display_name=self.display_name, role=self.role
        )


class UserStore(Protocol):
    def get_by_username(self, username: str) -> User | None: ...

    def get_by_id(self, user_id: str) -> User | None: ...


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    return hmac.compare_digest(candidate, bytes.fromhex(digest))


# Verified against when the username is unknown, so "no such user" and "wrong password"
# take the same time and give the same answer.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class MemoryUserStore:
    def __init__(self, users: list[User]):
        self._by_name = {u.username: u for u in users}
        self._by_id = {u.id: u for u in users}

    def get_by_username(self, username: str) -> User | None:
        return self._by_name.get(username)

    def get_by_id(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class TokenService:
    def __init__(self, secret: str, ttl_minutes: int):
        self._secret = secret.encode()
        self.ttl = timedelta(minutes=ttl_minutes)

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._secret, body.encode(), hashlib.sha256).digest())

    def issue(self, user: User, now: datetime) -> tuple[str, datetime]:
        expires = now + self.ttl
        body = _b64(json.dumps({"sub": user.id, "exp": int(expires.timestamp())}).encode())
        return f"{body}.{self._sign(body)}", expires

    def verify(self, token: str, now: datetime) -> str:
        """The user id in a valid, unexpired token; Unauthorized otherwise."""
        try:
            body, signature = token.split(".")
            if not hmac.compare_digest(signature, self._sign(body)):
                raise ValueError("bad signature")
            claims = json.loads(_unb64(body))
            if claims["exp"] <= now.timestamp():
                raise Unauthorized("Your session has expired. Sign in again.")
            return claims["sub"]
        except Unauthorized:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise Unauthorized("Invalid credentials.") from exc


def authenticate(store: UserStore, username: str, password: str) -> User:
    user = store.get_by_username(username)
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise Unauthorized("Incorrect username or password.")
    return user


def current_user(request: Request) -> User:
    """Dependency for every protected route."""
    ctx = request.app.state.ctx
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Sign in to do this.", headers={"WWW-Authenticate": "Bearer"})
    user = ctx.users.get_by_id(ctx.tokens.verify(token, datetime.now(UTC)))
    if user is None:
        raise Unauthorized("Invalid credentials.", headers={"WWW-Authenticate": "Bearer"})
    request.state.user_id = user.id
    return user
