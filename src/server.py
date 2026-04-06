"""AiCC MCP Server -- entry point.

Registers all 22 tools with the MCP SDK, mounts auth middleware,
adds health check endpoint, and runs via Streamable HTTP transport.
"""

import logging
import time
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from src import config, db
from src.auth import AuthMiddleware, current_user
from src.exceptions import (
    AzDevOpsAPIError,
    AzDevOpsNotConfiguredError,
    AuthError,
    FileAlreadyExistsError,
    FileNotFoundError_,
    GitHubAPIError,
    InvalidModeError,
    UserDisabledError,
    error_response,
)
from src.tools import content, identity, work_items

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
config.setup_logging()
config.validate_config()

logger = logging.getLogger("server")

# Initialize database
db.init_db()

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="aicc-mcp",
    instructions=(
        "AI Command Center MCP Server. Provides tools for managing AI partner "
        "identity, content, and work items. Use load_context() at the start of "
        "every conversation to get full context."
    ),
    host="0.0.0.0",
    port=config.PORT,
    stateless_http=True,
)


# ---------------------------------------------------------------------------
# Helper: get user from context var
# ---------------------------------------------------------------------------
def _get_user():
    """Get the authenticated user from the context variable."""
    user = current_user.get()
    if user is None:
        raise AuthError("No authenticated user in context")
    return user


def _handle_tool_error(e: Exception) -> dict:
    """Convert exceptions to structured MCP error responses."""
    if isinstance(e, FileNotFoundError_):
        return error_response("FILE_NOT_FOUND", str(e), {"path": e.path})
    elif isinstance(e, FileAlreadyExistsError):
        return error_response("FILE_ALREADY_EXISTS", str(e), {"path": e.path})
    elif isinstance(e, InvalidModeError):
        return error_response("INVALID_MODE", str(e), {"mode": e.mode})
    elif isinstance(e, AzDevOpsNotConfiguredError):
        return error_response(
            "AZDEVOPS_NOT_CONFIGURED",
            "Work item tracking not configured for this user.",
        )
    elif isinstance(e, AzDevOpsAPIError):
        code = "AZDEVOPS_AUTH_FAILED" if e.status_code == 401 else "AZDEVOPS_ERROR"
        return error_response(code, e.message)
    elif isinstance(e, GitHubAPIError):
        if e.status_code == 404:
            return error_response("FILE_NOT_FOUND", e.message, {"path": e.path})
        elif e.status_code == 409:
            return error_response("CONFLICT", e.message)
        else:
            return error_response("GITHUB_ERROR", e.message)
    elif isinstance(e, ValueError):
        return error_response("VALIDATION_ERROR", str(e))
    else:
        logger.exception(f"Unhandled tool error: {e}")
        return error_response("INTERNAL_ERROR", "An internal error occurred.")


# ---------------------------------------------------------------------------
# Identity Tools (9)
# ---------------------------------------------------------------------------
@mcp.tool(
    name="load_context",
    description=(
        "Load the full AI partner context for a conversation. Returns: identity rules "
        "(the non-negotiable behavioral rules for every conversation), current status "
        "(all active work, deadlines, recent decisions), and the personality for the "
        "given mode (behavioral rules specific to this conversation's focus area).\n\n"
        "Call this at the start of every conversation. Also call this mid-conversation "
        "when your understanding of the context feels degraded or stale -- this is "
        "called 're-grounding.'\n\n"
        "If mode is not provided, returns the list of available personalities with "
        "their trigger keywords so you can match the conversation topic to the right "
        "personality.\n\n"
        "When mode IS provided, returns: identity rules + current status + the "
        "personality's behavioral rules + all files the personality references as "
        "boot-time context (e.g., checklists, workbooks, plans). This is a fat call "
        "by design -- one call gives you everything you need to be a full partner."
    ),
)
async def tool_load_context(mode: str | None = None) -> dict:
    try:
        user = _get_user()
        return await identity.load_context(user, mode)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="get_identity_rules",
    description=(
        "Get the core identity and behavioral rules that apply in every conversation "
        "regardless of mode. These define: who the human partner is, how they work, "
        "how the AI should communicate, and non-negotiable rules that must never be "
        "violated.\n\n"
        "These rules are universal. They do not change between modes. If you need "
        "mode-specific behavioral rules, use get_personality() instead."
    ),
)
async def tool_get_identity_rules() -> dict:
    try:
        user = _get_user()
        return await identity.get_identity_rules(user)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="update_identity_rules",
    description=(
        "Update the core identity rules that apply across all modes. Use this when a "
        "conversation reveals a new universal rule -- something that should apply in "
        "every future conversation regardless of mode.\n\n"
        "The test: 'Would this rule apply if I were in a completely different mode?' "
        "If yes, update identity rules. If no, update the personality for the current "
        "mode instead."
    ),
)
async def tool_update_identity_rules(content: str, change_summary: str) -> dict:
    try:
        user = _get_user()
        return await identity.update_identity_rules(user, content, change_summary)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="get_current_status",
    description=(
        "Get the current status of all active work, deadlines, recent decisions, and "
        "open items across every mode. This is the shared state that all conversations "
        "see.\n\n"
        "This is read-only. Status is updated by an external synthesis process, not by "
        "individual conversations. If you notice the status seems stale, tell the "
        "human -- do not attempt to update it yourself."
    ),
)
async def tool_get_current_status() -> dict:
    try:
        user = _get_user()
        return await identity.get_current_status(user)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="get_personalities",
    description=(
        "Get all available personalities with their names, descriptions, and trigger "
        "keywords. Use this to understand what personalities exist and to match a "
        "conversation topic to the right one.\n\n"
        "Only returns active personalities (those with behavioral rules and their own "
        "chat sessions). Does not return tracking areas or ideas -- those are separate "
        "concepts accessible through work item operations."
    ),
)
async def tool_get_personalities() -> dict:
    try:
        user = _get_user()
        return await identity.get_personalities(user)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="get_personality",
    description=(
        "Get the behavioral rules and context for a specific personality mode. Each "
        "mode defines: the conversation's focus area, tone and communication style, "
        "domain-specific rules, files to reference, and how to operate within that domain."
    ),
)
async def tool_get_personality(mode: str) -> dict:
    try:
        user = _get_user()
        return await identity.get_personality(user, mode)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="update_personality",
    description=(
        "Update the behavioral rules for a specific personality mode. Use this when a "
        "conversation reveals a new rule that applies only to this mode -- not "
        "universally.\n\n"
        "The test: 'Would this rule apply in every mode?' If yes, use "
        "update_identity_rules() instead."
    ),
)
async def tool_update_personality(
    mode: str, content: str, change_summary: str
) -> dict:
    try:
        user = _get_user()
        return await identity.update_personality(user, mode, content, change_summary)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="get_recent_activity",
    description=(
        "Get a summary of recent changes to the project. Returns the most recent "
        "commits with their messages, showing what was changed, by whom, and when.\n\n"
        "Use this at the start of a conversation to understand what happened since the "
        "last session, or mid-conversation to check if something was recently modified."
    ),
)
async def tool_get_recent_activity(count: int = 20) -> dict:
    try:
        user = _get_user()
        return await identity.get_recent_activity(user, count)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="detect_mode",
    description=(
        "Given a user's opening message, determine which personality mode best matches "
        "the conversation topic. Returns the recommended mode name and confidence level.\n\n"
        "Use this when the user starts a conversation without explicitly naming a mode. "
        "The server matches the message against each personality's trigger keywords and "
        "returns the best match.\n\n"
        "A smarter model (Claude, GPT-4) may not need this -- it can read trigger "
        "keywords from get_personalities() and match itself. But a smaller model (14B) "
        "may struggle with multi-step matching, so this tool does it server-side."
    ),
)
async def tool_detect_mode(message: str) -> dict:
    try:
        user = _get_user()
        return await identity.detect_mode(user, message)
    except Exception as e:
        return _handle_tool_error(e)


# ---------------------------------------------------------------------------
# Content Tools (6)
# ---------------------------------------------------------------------------
@mcp.tool(
    name="list_content",
    description=(
        "List the contents of a directory in the project. Returns file and folder names "
        "with basic metadata (type, size).\n\n"
        "Use this to explore what exists before reading or creating content. If no path "
        "is given, returns the top-level directory listing."
    ),
)
async def tool_list_content(path: str = "") -> dict:
    try:
        user = _get_user()
        return await content.list_content(user, path)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="get_document",
    description="Read the full contents of a document.",
)
async def tool_get_document(path: str) -> dict:
    try:
        user = _get_user()
        return await content.get_document(user, path)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="create_document",
    description=(
        "Create a new document. This will fail if a document already exists at the "
        "given path -- use update_document() to modify existing documents."
    ),
)
async def tool_create_document(
    path: str, content: str, commit_message: str
) -> dict:
    try:
        user = _get_user()
        return await content.create_document(user, path, content, commit_message)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="update_document",
    description=(
        "Update an existing document. This will fail if no document exists at the "
        "given path -- use create_document() for new files."
    ),
)
async def tool_update_document(
    path: str, content: str, commit_message: str
) -> dict:
    try:
        user = _get_user()
        return await content.update_document(user, path, content, commit_message)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="move_document",
    description="Move or rename a document or folder.",
)
async def tool_move_document(
    from_path: str, to_path: str, commit_message: str
) -> dict:
    try:
        user = _get_user()
        return await content.move_document(user, from_path, to_path, commit_message)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="delete_document",
    description=(
        "Delete a document. This is irreversible. The AI should confirm with the human "
        "before calling this."
    ),
)
async def tool_delete_document(path: str, commit_message: str) -> dict:
    try:
        user = _get_user()
        return await content.delete_document(user, path, commit_message)
    except Exception as e:
        return _handle_tool_error(e)


# ---------------------------------------------------------------------------
# Work Item Tools (7)
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_tracking_areas",
    description=(
        "Get all valid work areas the user can assign work items to. Returns area name, "
        "full area path, and which personality handles it.\n\n"
        "Call this before creating work items so you know what areas exist rather than "
        "guessing names."
    ),
)
async def tool_get_tracking_areas() -> dict:
    try:
        user = _get_user()
        return await work_items.get_tracking_areas(user)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="list_work_items",
    description=(
        "List work items, optionally filtered. Returns a summary list with ID, title, "
        "state, priority, and area."
    ),
)
async def tool_list_work_items(
    area: str | None = None,
    state: str | None = None,
    priority: int | None = None,
    tags: str | None = None,
) -> dict:
    try:
        user = _get_user()
        return await work_items.list_work_items_tool(
            user, area=area, state=state, priority=priority, tags=tags
        )
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="get_work_item",
    description=(
        "Get full details of a specific work item including description, comments, "
        "and history."
    ),
)
async def tool_get_work_item(id: int) -> dict:
    try:
        user = _get_user()
        return await work_items.get_work_item_tool(user, id)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="create_work_item",
    description=(
        "Create a new work item for tracking. Use get_tracking_areas() first to see "
        "valid area names."
    ),
)
async def tool_create_work_item(
    title: str,
    description: str,
    area: str,
    priority: int = 3,
    tags: str | None = None,
) -> dict:
    try:
        user = _get_user()
        return await work_items.create_work_item_tool(
            user,
            title=title,
            description=description,
            area=area,
            priority=priority,
            tags=tags,
        )
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="update_work_item",
    description=(
        "Update a work item's fields. The AI should NEVER close a work item without "
        "explicit human confirmation."
    ),
)
async def tool_update_work_item(id: int, changes: dict) -> dict:
    try:
        user = _get_user()
        return await work_items.update_work_item_tool(user, id, changes)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="add_comment",
    description=(
        "Add a comment to a work item. Comments are the primary way context gets "
        "passed between conversations and sessions. Write comments that a future AI "
        "session (or the human) can understand without additional context."
    ),
)
async def tool_add_comment(id: int, text: str) -> dict:
    try:
        user = _get_user()
        return await work_items.add_comment_tool(user, id, text)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="log_daily_summary",
    description=(
        "Log a daily summary of what was accomplished, decided, and left open. This "
        "creates a work item tagged 'daily-log' with today's date, or adds to an "
        "existing one if a daily log already exists for today.\n\n"
        "Call this at the end of a working session when the human asks for a daily log."
    ),
)
async def tool_log_daily_summary(summary: str) -> dict:
    try:
        user = _get_user()
        return await work_items.log_daily_summary_tool(user, summary)
    except Exception as e:
        return _handle_tool_error(e)


# ---------------------------------------------------------------------------
# Health Check (custom route, not an MCP tool)
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for monitoring and deployment verification."""
    db_healthy = db.check_health()

    checks = {
        "database": "healthy" if db_healthy else "unhealthy",
        "github_api": "unknown",
        "azdevops_api": "unknown",
    }

    status = "healthy" if db_healthy else "degraded"

    return JSONResponse(
        content={
            "status": status,
            "version": config.VERSION,
            "checks": checks,
        }
    )


# ---------------------------------------------------------------------------
# Build the combined ASGI application
# ---------------------------------------------------------------------------
def create_app() -> Starlette:
    """Create the full ASGI application with auth middleware and MCP routes."""
    # Get the MCP Starlette app
    mcp_app = mcp.streamable_http_app()

    # Wrap with auth middleware
    # We need to intercept requests before they hit MCP to inject the user
    from starlette.middleware import Middleware

    app = Starlette(
        routes=mcp_app.routes,
        middleware=[
            Middleware(AuthMiddleware),
        ],
        exception_handlers=mcp_app.exception_handlers if hasattr(mcp_app, 'exception_handlers') else {},
    )

    return app


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
app = create_app()

if __name__ == "__main__":
    logger.info(
        f"Starting AiCC MCP Server v{config.VERSION} on port {config.PORT}"
    )

    # Check for active users
    users = db.list_users()
    active_count = sum(1 for u in users if u.get("active"))
    if active_count == 0:
        logger.warning(
            "No active users. Run: python -m src.admin.cli add ... to add users."
        )
    else:
        logger.info(f"Active users: {active_count}")

    uvicorn.run(
        "src.server:app",
        host="0.0.0.0",
        port=config.PORT,
        log_level=config.LOG_LEVEL.lower(),
    )
