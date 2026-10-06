"""FastAPI dependencies: the services, a database connection per request, the
current user, and rate limits."""

from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from heatwave_api.config import parse_rate
from heatwave_api.db.repository import Repository
from heatwave_api.errors import RateLimited, ServiceNotReady, Unauthenticated
from heatwave_api.services import Services

bearer = HTTPBearer(auto_error=False, description="Token from POST /api/v1/auth/login")


def get_services(request: Request) -> Services:
    services = getattr(request.app.state, "services", None)
    if services is None:  # only reachable if startup was bypassed
        raise ServiceNotReady("The service is still starting.")
    return services


def get_repo(services: Services = Depends(get_services)) -> Iterator[Repository]:
    with services.db.connect() as conn:
        yield Repository(conn)


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
) -> dict:
    """The signed-in user, or 401. The server-side check every write goes through."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthenticated()
    claims = services.tokens.decode(credentials.credentials)
    if repo.is_revoked(claims["jti"]):
        raise Unauthenticated("You have signed out. Sign in again.", code="TOKEN_REVOKED")
    user = repo.user_by_id(int(claims["sub"]))
    if user is None or not user["active"]:
        raise Unauthenticated("This account is no longer active.", code="INVALID_TOKEN")
    request.state.log_fields = getattr(request.state, "log_fields", {}) | {"user": user["username"]}
    return user | {"_claims": claims}


def reader(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    services: Services = Depends(get_services),
    repo: Repository = Depends(get_repo),
) -> dict | None:
    """Dashboard reads: open unless AUTH_REQUIRED_FOR_READS=true (Part 15 decides)."""
    if not services.settings.auth_required_for_reads:
        return None
    return current_user(request, credentials, services, repo)


def rate_limit(bucket: str) -> Callable[..., None]:
    """A dependency enforcing settings.rate_limit_<bucket> per client address."""

    def check(request: Request, services: Services = Depends(get_services)) -> None:
        limit, period = parse_rate(getattr(services.settings, f"rate_limit_{bucket}"))
        client = request.client.host if request.client else "unknown"
        retry_after = services.limiter.hit(bucket, client, limit, period)
        if retry_after is not None:
            raise RateLimited(
                f"Too many requests. Try again in {retry_after} s.",
                headers={"Retry-After": str(retry_after)},
                details={"retry_after_s": retry_after},
            )

    return check
