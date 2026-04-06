"""API key authentication middleware."""

import logging
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.db import UserConfig, lookup_user, lookup_user_any

logger = logging.getLogger("auth")

# Context variable to hold the authenticated user for the current request
current_user: ContextVar[UserConfig | None] = ContextVar("current_user", default=None)

# Paths that don't require authentication
PUBLIC_PATHS = {"/health", "/favicon.ico"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Extract and validate API key from Authorization header."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Extract API key from Authorization header
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning(
                f"Missing or malformed Authorization header from {request.client.host}"
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": True,
                    "code": "AUTH_FAILED",
                    "message": "Missing or malformed Authorization header. Expected: Bearer <api_key>",
                },
            )

        api_key = auth_header[7:]  # Strip "Bearer "

        # Check if user exists (including disabled)
        user_any = lookup_user_any(api_key)
        if user_any and not user_any.active:
            logger.warning(f"Disabled user attempted access: {user_any.name}")
            return JSONResponse(
                status_code=403,
                content={
                    "error": True,
                    "code": "USER_DISABLED",
                    "message": "This account has been disabled. Contact the administrator.",
                },
            )

        # Look up active user
        user = lookup_user(api_key)
        if user is None:
            logger.warning(
                f"Invalid API key attempted from {request.client.host}"
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": True,
                    "code": "AUTH_FAILED",
                    "message": "Invalid API key.",
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
