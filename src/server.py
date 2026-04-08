"""AiCC MCP Server -- entry point.

Registers all 30 tools with the MCP SDK, mounts auth middleware,
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": False, "destructiveHint": False},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": False, "destructiveHint": False},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": False, "destructiveHint": False},
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
    annotations={"readOnlyHint": False, "destructiveHint": False},
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
    annotations={"readOnlyHint": False, "destructiveHint": True},
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
    annotations={"readOnlyHint": False, "destructiveHint": True},
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
# Work Item Tools (15)
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_tracking_areas",
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": True, "idempotentHint": True},
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
    annotations={"readOnlyHint": False, "destructiveHint": False},
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
    annotations={"readOnlyHint": False, "destructiveHint": False},
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
    annotations={"readOnlyHint": False, "destructiveHint": False},
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
    annotations={"readOnlyHint": False, "destructiveHint": False},
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


@mcp.tool(
    name="close_work_item",
    annotations={"readOnlyHint": False, "destructiveHint": True},
    description=(
        "Close a work item by transitioning it to Done. NEVER close a work item "
        "without explicit human confirmation. Always ask first."
    ),
)
async def tool_close_work_item(id: int) -> dict:
    try:
        user = _get_user()
        return await work_items.close_work_item_tool(user, id)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="reopen_work_item",
    annotations={"readOnlyHint": False, "destructiveHint": False},
    description=(
        "Reopen a work item by transitioning it back to To Do from Done. Use this "
        "when a closed item needs to be revisited."
    ),
)
async def tool_reopen_work_item(id: int) -> dict:
    try:
        user = _get_user()
        return await work_items.reopen_work_item_tool(user, id)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="search_work_items",
    annotations={"readOnlyHint": True, "idempotentHint": True},
    description=(
        "Search work items by keyword across title and description. Returns matching "
        "items sorted by most recently changed.\n\n"
        "Use this when you need to find work items by topic rather than structured "
        "filters. For filtering by area, state, priority, or tags, use list_work_items() "
        "instead."
    ),
)
async def tool_search_work_items(query: str) -> dict:
    try:
        user = _get_user()
        return await work_items.search_work_items_tool(user, query)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="attach_file",
    annotations={"readOnlyHint": False, "destructiveHint": False},
    description=(
        "Attach a file to a work item. The file content is provided as text. "
        "Use this to attach logs, reports, or other text-based artifacts to a "
        "work item for reference."
    ),
)
async def tool_attach_file(id: int, filename: str, content: str) -> dict:
    try:
        user = _get_user()
        return await work_items.attach_file_tool(user, id, filename, content)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="list_attachments",
    annotations={"readOnlyHint": True, "idempotentHint": True},
    description="List all attachments on a work item.",
)
async def tool_list_attachments(id: int) -> dict:
    try:
        user = _get_user()
        return await work_items.list_attachments_tool(user, id)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="edit_comment",
    annotations={"readOnlyHint": False, "destructiveHint": False},
    description=(
        "Edit an existing comment on a work item. Use get_work_item() first to see "
        "comment IDs. Use this to correct typos or update information in a previously "
        "posted comment."
    ),
)
async def tool_edit_comment(id: int, comment_id: int, text: str) -> dict:
    try:
        user = _get_user()
        return await work_items.edit_comment_tool(user, id, comment_id, text)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="cascade",
    annotations={"readOnlyHint": False, "destructiveHint": False},
    description=(
        "Create a cascade work item with checklist steps for a specific event type. "
        "Reads the cascade checklist from the project, extracts the relevant section, "
        "and creates a P1 work item with all steps as checkboxes.\n\n"
        "Valid cascade types: article, book, linkedin, narrative, product, workstream, "
        "session-close, resume, zenodo.\n\n"
        "Example: cascade('article', 'Publish Article 6: Copilot validates Intent Layer')"
    ),
)
async def tool_cascade(type: str, title: str) -> dict:
    try:
        user = _get_user()
        return await work_items.cascade_tool(user, type, title)
    except Exception as e:
        return _handle_tool_error(e)


@mcp.tool(
    name="daily_logs",
    annotations={"readOnlyHint": True, "idempotentHint": True},
    description=(
        "Show recent daily log entries with their comments. Returns daily logs from "
        "the last N days, each with all comments (which contain the actual session "
        "summaries).\n\n"
        "Daily logs are the richest source of session context. Use this to understand "
        "what happened in recent sessions."
    ),
)
async def tool_daily_logs(days: int = 7) -> dict:
    try:
        user = _get_user()
        return await work_items.daily_logs_tool(user, days)
    except Exception as e:
        return _handle_tool_error(e)


# ---------------------------------------------------------------------------
# Public tools listing (no auth required, used by OAuth consent page)
# ---------------------------------------------------------------------------
@mcp.custom_route("/tools", methods=["GET"])
async def list_tools_public(request: Request) -> JSONResponse:
    """Public endpoint listing tools with annotations for OAuth consent page."""
    registered = await mcp.list_tools()
    tools = []
    for tool in registered:
        annotations = {}
        if tool.annotations:
            annotations = tool.annotations.model_dump(exclude_none=True)
        tools.append({
            "name": tool.name,
            "description": (tool.description or "")[:100],
            "annotations": annotations,
        })
    return JSONResponse(content={"tools": tools})


# ---------------------------------------------------------------------------
# OAuth Discovery (well-known endpoints on the MCP domain)
# These tell claude.ai where to find our authorization server (the website).
# ---------------------------------------------------------------------------
@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_protected_resource(request: Request) -> JSONResponse:
    """RFC 9728: Protected Resource Metadata."""
    return JSONResponse(content={
        "resource": "https://mcp.theintentlayer.com/mcp",
        "authorization_servers": ["https://theintentlayer.com"],
        "scopes_supported": ["mcp:tools", "mcp:resources"],
    })


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def oauth_auth_server_metadata(request: Request) -> JSONResponse:
    """RFC 8414: Authorization Server Metadata (points to the website)."""
    return JSONResponse(content={
        "issuer": "https://theintentlayer.com",
        "authorization_endpoint": "https://theintentlayer.com/oauth/authorize",
        "token_endpoint": "https://theintentlayer.com/oauth/token",
        "registration_endpoint": "https://theintentlayer.com/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["mcp:tools", "mcp:resources"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


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
# Build the ASGI application
# ---------------------------------------------------------------------------
# Get the MCP Starlette app (preserves lifespan and task group initialization)
app = mcp.streamable_http_app()

# Add auth middleware directly to the MCP app
app.add_middleware(AuthMiddleware)

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
