"""Authentication middleware -- supports API keys and OAuth JWT tokens."""

import logging
from contextvars import ContextVar

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src import config
from src.db import UserConfig, lookup_user, lookup_user_any, lookup_user_by_account

logger = logging.getLogger("auth")

# Context variable to hold the authenticated user for the current request
current_user: ContextVar[UserConfig | None] = ContextVar("current_user", default=None)

# Paths that don't require authentication
PUBLIC_PATHS = {"/health", "/favicon.ico"}

# Well-known paths that must be public for OAuth discovery
WELLKNOWN_PREFIXES = ("/.well-known/",)


class AuthMiddleware(BaseHTTPMiddleware):
    """Dual auth: API key (Copilot Studio, local LLMs) or JWT (claude.ai OAuth)."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Skip auth for well-known OAuth discovery endpoints
        for prefix in WELLKNOWN_PREFIXES:
            if request.url.path.startswith(prefix):
                return await call_next(request)

        # Extract Bearer token from Authorization header
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            # No Bearer token -- return 401 with resource metadata hint for OAuth
            logger.warning(
                f"Missing or malformed Authorization header from {request.client.host}"
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": True,
                    "code": "AUTH_FAILED",
                    "message": "Missing or malformed Authorization header. Expected: Bearer <token>",
                },
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata='
                        '"https://mcp.theintentlayer.com/.well-known/oauth-protected-resource"'
                    )
                },
            )

        bearer_token = auth_header[7:]  # Strip "Bearer "

        # Try 1: API key lookup (for Copilot Studio, local LLMs, direct API)
        user = self._try_api_key(bearer_token)

        # Try 2: JWT validation (for claude.ai OAuth flow)
        if user is None and config.JWT_SECRET:
            user = self._try_jwt(bearer_token)

        # Neither worked
        if user is None:
            logger.warning(
                f"Invalid token from {request.client.host}"
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": True,
                    "code": "AUTH_FAILED",
                    "message": "Invalid token.",
                },
            )

        # Check if disabled
        if not user.active:
            logger.warning(f"Disabled user attempted access: {user.name}")
            return JSONResponse(
                status_code=403,
                content={
                    "error": True,
                    "code": "USER_DISABLED",
                    "message": "This account has been disabled.",
                },
            )

        # Attach user to request state and context var
        request.state.user = user
        request.state.user_name = user.name
        token = current_user.set(user)

        try:
            response = await call_next(request)
            return response
        finally:
            current_user.reset(token)

    def _try_api_key(self, token: str) -> UserConfig | None:
        """Try to authenticate with the token as an API key."""
        if not token.startswith("aicc-"):
            return None
        return lookup_user(token)

    def _try_jwt(self, token: str) -> UserConfig | None:
        """Try to authenticate with the token as a JWT from the OAuth flow."""
        try:
            payload = jwt.decode(
                token,
                config.JWT_SECRET,
                algorithms=["HS256"],
                audience="https://mcp.theintentlayer.com/mcp",
                issuer="https://theintentlayer.com",
            )
            account_id = payload.get("sub")
            if account_id is None:
                logger.warning("JWT missing sub claim")
                return None

            user = lookup_user_by_account(int(account_id))
            if user:
                logger.info(f"JWT auth successful for account {account_id} -> user {user.name}")
            else:
                logger.warning(f"JWT valid but no linked MCP user for account {account_id}")
            return user

        except jwt.ExpiredSignatureError:
            logger.debug("JWT expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug(f"JWT validation failed: {e}")
            return None
