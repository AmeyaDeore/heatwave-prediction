"""Password hashing and signed session tokens (the parts of Part 15 that Part 07 needs
to gate writes). Standard library only: hashlib.scrypt and HMAC-SHA256.

Tokens are JWTs (HS256) carrying the user id, username, role, expiry and a token id
(``jti``). The service keeps no session state: a token is valid if its signature,
issuer and expiry check out, its ``jti`` has not been revoked by a logout, and its
user is still active.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime
from functools import lru_cache

from heatwave_api.errors import Unauthenticated

ISSUER = "heatwave-api"
# scrypt cost parameters (OWASP's minimum recommendation, ~50 ms per hash).
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2**14, 8, 1, 32


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(expected)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, _unb64(expected))


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """Verified against when the username does not exist, so a login for an unknown
    user takes as long as a wrong password and cannot be used to enumerate users."""
    return hash_password(secrets.token_urlsafe(16))


class TokenService:
    def __init__(self, secret: str, ttl_minutes: int, clock=time.time):
        self._key = secret.encode("utf-8")
        self.ttl_seconds = ttl_minutes * 60
        self._clock = clock

    def _sign(self, signing_input: bytes) -> str:
        return _b64(hmac.new(self._key, signing_input, hashlib.sha256).digest())

    def issue(self, user: dict) -> tuple[str, datetime, str]:
        """A token for ``user`` (a users row). Returns (token, expires_at, jti)."""
        now = int(self._clock())
        jti = secrets.token_hex(16)
        claims = {
            "iss": ISSUER,
            "sub": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
            "iat": now,
            "exp": now + self.ttl_seconds,
            "jti": jti,
        }
        header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
        signing_input = f"{header}.{payload}".encode("ascii")
        token = f"{header}.{payload}.{self._sign(signing_input)}"
        return token, datetime.fromtimestamp(claims["exp"], UTC), jti

    def decode(self, token: str) -> dict:
        """The claims of a valid token, or Unauthenticated. Never says which check failed
        beyond "expired" vs "invalid", which the frontend needs to tell apart."""
        invalid = Unauthenticated(
            "The session token is not valid. Sign in again.", code="INVALID_TOKEN"
        )
        try:
            header, payload, signature = token.split(".")
            signing_input = f"{header}.{payload}".encode("ascii")
            if not hmac.compare_digest(self._sign(signing_input), signature):
                raise invalid
            if json.loads(_unb64(header)) != {"alg": "HS256", "typ": "JWT"}:
                raise invalid
            claims = json.loads(_unb64(payload))
        except (ValueError, UnicodeError):
            raise invalid from None
        if claims.get("iss") != ISSUER or not {"sub", "exp", "jti"} <= claims.keys():
            raise invalid
        if claims["exp"] <= self._clock():
            raise Unauthenticated("Your session has expired. Sign in again.", code="TOKEN_EXPIRED")
        return claims
