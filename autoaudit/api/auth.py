"""Authentication placeholder (Week 8 requirement).

This is intentionally a placeholder, not a production auth system: no
users, no sessions, no roles — a single shared API key checked via a
constant-time comparison. It exists so the API isn't wide open by default
in any deployment where `AUTOAUDIT_API_KEY` is set, and so a real
auth provider (OAuth/JWT/SSO) has an obvious single place to be swapped in
later (`verify_api_key` below is the only thing that would change).

Behavior:
- `AUTOAUDIT_API_KEY` unset (default): auth is disabled, every request is
  allowed through — matches every earlier milestone's documented "no auth"
  state, so existing deployments/tests aren't broken by this addition.
- `AUTOAUDIT_API_KEY` set: every `/api/*` request except `/api/health` must
  send `Authorization: Bearer <key>` matching exactly, or gets a 401.
"""
from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .dependencies import get_config

# Paths reachable without a key even when AUTOAUDIT_API_KEY is set — docs
# and the health check need to stay reachable for uptime monitoring/first-
# time setup regardless of auth configuration.
_EXEMPT_PATHS = {"/api/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def verify_api_key(provided: str | None, expected: str) -> bool:
    """Constant-time comparison so response timing can't be used to guess
    the key one character at a time."""
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Resolve get_config the same way FastAPI's Depends() would —
        # respecting app.dependency_overrides — since middleware sits
        # outside the Depends system and would otherwise always see the
        # process-wide lru_cache'd config, breaking per-test isolation.
        config_factory = request.app.dependency_overrides.get(get_config, get_config)
        config = config_factory()

        if not config.api_key:
            return await call_next(request)  # auth disabled — default state

        if request.url.path in _EXEMPT_PATHS or not request.url.path.startswith("/api/"):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        provided = header[7:] if header.lower().startswith("bearer ") else None

        if not verify_api_key(provided, config.api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid API key. Send 'Authorization: Bearer <key>'."},
            )

        return await call_next(request)
