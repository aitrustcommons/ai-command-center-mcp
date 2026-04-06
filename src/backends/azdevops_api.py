"""Azure DevOps REST API backend. Work item operations go through here."""

import base64
import logging
import time
from datetime import datetime

import httpx

from src.db import UserConfig
from src.exceptions import AzDevOpsAPIError, AzDevOpsNotConfiguredError

logger = logging.getLogger("azdevops")

API_VERSION = "7.1"
COMMENT_API_VERSION = "7.1-preview.4"
TIMEOUT = 30.0


def _check_configured(user: UserConfig) -> None:
    """Raise if user has no AZ DevOps credentials."""
    if not user.az_pat or not user.az_org or not user.az_project:
        raise AzDevOpsNotConfiguredError()


def _base_url(user: UserConfig) -> str:
    """Build the org-level base URL."""
    return f"https://dev.azure.com/{user.az_org}"


def _headers(user: UserConfig) -> dict:
    """Build auth headers (Basic auth with PAT)."""
    credentials = base64.b64encode(f":{user.az_pat}".encode()).decode("ascii")
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }


def _patch_headers(user: UserConfig) -> dict:
    """Headers for JSON Patch operations."""
    credentials = base64.b64encode(f":{user.az_pat}".encode()).decode("ascii")
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json-patch+json",
    }


def _convert_newlines(text: str) -> str:
    """Convert \\n to <br> for AZ DevOps text fields.

    AZ DevOps silently drops plain newlines in comments and descriptions.
    This was a known bug fixed in az_ops.py on April 5, 2026.
    """
    return text.replace("\n", "<br>")


def _full_area_path(user: UserConfig, area: str) -> str:
    """Build full area path by prepending project name.

    Input: "CueSpan" -> "The Big Push\\CueSpan"
    Input: "AI-Trust-Commons\\OmniSynth" -> "The Big Push\\AI-Trust-Commons\\OmniSynth"
    """
    return f"{user.az_project}\\{area}"


async def wiql_query(user: UserConfig, wiql: str) -> list[int]:
    """Execute a WIQL query and return work item IDs."""
    _check_configured(user)

    start = time.time()
    url = f"{_base_url(user)}/{user.az_project}/_apis/wit/wiql?api-version={API_VERSION}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            url, headers=_headers(user), json={"query": wiql}
        )

    duration_ms = int((time.time() - start) * 1000)

    if response.status_code == 401:
        logger.error(f"[{user.name}] AZDEVOPS wiql_query -> 401 ({duration_ms}ms)")
        raise AzDevOpsAPIError(401, "Azure DevOps authentication failed")

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] AZDEVOPS wiql_query -> {response.status_code} ({duration_ms}ms)"
        )
        raise AzDevOpsAPIError(response.status_code, response.text)

    logger.info(f"[{user.name}] AZDEVOPS wiql_query -> 200 ({duration_ms}ms)")

    data = response.json()
    return [item["id"] for item in data.get("workItems", [])]


async def get_work_items_batch(user: UserConfig, ids: list[int]) -> list[dict]:
    """Batch-fetch work item details by IDs."""
    _check_configured(user)

    if not ids:
        return []

    # AZ DevOps batch limit is 200
    start = time.time()
    ids_str = ",".join(str(i) for i in ids[:200])
    url = (
        f"{_base_url(user)}/{user.az_project}/_apis/wit/workitems"
        f"?ids={ids_str}&$expand=all&api-version={API_VERSION}"
    )

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_headers(user))

    duration_ms = int((time.time() - start) * 1000)

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] AZDEVOPS get_work_items_batch "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise AzDevOpsAPIError(response.status_code, response.text)

    logger.info(
        f"[{user.name}] AZDEVOPS get_work_items_batch ({len(ids)} items) "
        f"-> 200 ({duration_ms}ms)"
    )

    data = response.json()
    return data.get("value", [])


async def get_work_item(user: UserConfig, work_item_id: int) -> dict:
    """Get a single work item with full details."""
    _check_configured(user)

    start = time.time()
    url = (
        f"{_base_url(user)}/{user.az_project}/_apis/wit/workitems/{work_item_id}"
        f"?$expand=all&api-version={API_VERSION}"
    )

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_headers(user))

    duration_ms = int((time.time() - start) * 1000)

    if response.status_code == 404:
        logger.info(
            f"[{user.name}] AZDEVOPS get_work_item {work_item_id} "
            f"-> 404 ({duration_ms}ms)"
        )
        raise AzDevOpsAPIError(404, f"Work item {work_item_id} not found", work_item_id)

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] AZDEVOPS get_work_item {work_item_id} "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise AzDevOpsAPIError(response.status_code, response.text, work_item_id)

    logger.info(
        f"[{user.name}] AZDEVOPS get_work_item {work_item_id} -> 200 ({duration_ms}ms)"
    )

    return response.json()


async def create_work_item(
    user: UserConfig,
    title: str,
    description: str,
    area: str,
    priority: int = 3,
    tags: str | None = None,
    work_item_type: str = "Issue",
) -> dict:
    """Create a new work item."""
    _check_configured(user)

    start = time.time()
    url = (
        f"{_base_url(user)}/{user.az_project}/_apis/wit/workitems"
        f"/${work_item_type}?api-version={API_VERSION}"
    )

    operations = [
        {"op": "add", "path": "/fields/System.Title", "value": title},
        {
            "op": "add",
            "path": "/fields/System.Description",
            "value": _convert_newlines(description),
        },
        {
            "op": "add",
            "path": "/fields/System.AreaPath",
            "value": _full_area_path(user, area),
        },
        {
            "op": "add",
            "path": "/fields/Microsoft.VSTS.Common.Priority",
            "value": priority,
        },
    ]

    if tags:
        operations.append(
            {"op": "add", "path": "/fields/System.Tags", "value": tags}
        )

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            url, headers=_patch_headers(user), json=operations
        )

    duration_ms = int((time.time() - start) * 1000)

    if response.status_code not in (200, 201):
        logger.error(
            f"[{user.name}] AZDEVOPS create_work_item -> {response.status_code} ({duration_ms}ms)"
        )
        raise AzDevOpsAPIError(response.status_code, response.text)

    logger.info(
        f"[{user.name}] AZDEVOPS create_work_item '{title}' -> {response.status_code} ({duration_ms}ms)"
    )

    return response.json()


async def update_work_item(
    user: UserConfig, work_item_id: int, changes: dict
) -> dict:
    """Update a work item's fields."""
    _check_configured(user)

    start = time.time()
    url = (
        f"{_base_url(user)}/{user.az_project}/_apis/wit/workitems/{work_item_id}"
        f"?api-version={API_VERSION}"
    )

    # Map friendly field names to AZ DevOps field paths
    field_map = {
        "title": "/fields/System.Title",
        "description": "/fields/System.Description",
        "state": "/fields/System.State",
        "priority": "/fields/Microsoft.VSTS.Common.Priority",
        "tags": "/fields/System.Tags",
        "area": "/fields/System.AreaPath",
    }

    operations = []
    for key, value in changes.items():
        field_path = field_map.get(key)
        if not field_path:
            continue

        # Convert newlines in text fields
        if key in ("description",) and isinstance(value, str):
            value = _convert_newlines(value)

        # Prefix area path
        if key == "area" and isinstance(value, str):
            value = _full_area_path(user, value)

        operations.append({"op": "replace", "path": field_path, "value": value})

    if not operations:
        raise ValueError("No valid fields to update")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.patch(
            url, headers=_patch_headers(user), json=operations
        )

    duration_ms = int((time.time() - start) * 1000)

    if response.status_code == 404:
        raise AzDevOpsAPIError(404, f"Work item {work_item_id} not found", work_item_id)

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] AZDEVOPS update_work_item {work_item_id} "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise AzDevOpsAPIError(response.status_code, response.text, work_item_id)

    logger.info(
        f"[{user.name}] AZDEVOPS update_work_item {work_item_id} -> 200 ({duration_ms}ms)"
    )

    return response.json()


async def add_comment(user: UserConfig, work_item_id: int, text: str) -> dict:
    """Add a comment to a work item. Converts newlines to <br>."""
    _check_configured(user)

    start = time.time()
    url = (
        f"{_base_url(user)}/{user.az_project}/_apis/wit/workitems/{work_item_id}"
        f"/comments?api-version={COMMENT_API_VERSION}"
    )

    body = {"text": _convert_newlines(text)}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(url, headers=_headers(user), json=body)

    duration_ms = int((time.time() - start) * 1000)

    if response.status_code == 404:
        raise AzDevOpsAPIError(
            404, f"Work item {work_item_id} not found", work_item_id
        )

    if response.status_code not in (200, 201):
        logger.error(
            f"[{user.name}] AZDEVOPS add_comment {work_item_id} "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise AzDevOpsAPIError(response.status_code, response.text, work_item_id)

    logger.info(
        f"[{user.name}] AZDEVOPS add_comment {work_item_id} -> {response.status_code} ({duration_ms}ms)"
    )

    return response.json()


async def list_work_items(
    user: UserConfig,
    area: str | None = None,
    state: str | None = None,
    priority: int | None = None,
    tags: str | None = None,
) -> list[dict]:
    """List work items with optional filters. Returns summary list."""
    _check_configured(user)

    # Build WIQL query
    conditions = [
        f"[System.TeamProject] = '{user.az_project}'",
        "[System.State] <> 'Removed'",
    ]

    if area:
        full_area = _full_area_path(user, area)
        conditions.append(f"[System.AreaPath] UNDER '{full_area}'")

    if state:
        conditions.append(f"[System.State] = '{state}'")

    if priority:
        conditions.append(f"[Microsoft.VSTS.Common.Priority] = {priority}")

    if tags:
        conditions.append(f"[System.Tags] CONTAINS '{tags}'")

    where_clause = " AND ".join(conditions)
    wiql = (
        f"SELECT [System.Id], [System.Title], [System.State], "
        f"[Microsoft.VSTS.Common.Priority], [System.AreaPath] "
        f"FROM WorkItems WHERE {where_clause} "
        f"ORDER BY [Microsoft.VSTS.Common.Priority] ASC, [System.Id] DESC"
    )

    ids = await wiql_query(user, wiql)

    if not ids:
        return []

    items = await get_work_items_batch(user, ids)

    return [
        {
            "id": item["id"],
            "title": item["fields"].get("System.Title", ""),
            "state": item["fields"].get("System.State", ""),
            "priority": item["fields"].get("Microsoft.VSTS.Common.Priority", 0),
            "area": item["fields"].get("System.AreaPath", ""),
            "tags": item["fields"].get("System.Tags", ""),
            "type": item["fields"].get("System.WorkItemType", ""),
        }
        for item in items
    ]


async def find_daily_log(user: UserConfig, date_str: str) -> int | None:
    """Find today's daily log work item. Returns work item ID or None."""
    _check_configured(user)

    wiql = (
        f"SELECT [System.Id] FROM WorkItems "
        f"WHERE [System.TeamProject] = '{user.az_project}' "
        f"AND [System.Title] CONTAINS 'Log: {date_str}' "
        f"AND [System.Tags] CONTAINS 'daily-log' "
        f"AND [System.State] <> 'Removed'"
    )

    ids = await wiql_query(user, wiql)
    return ids[0] if ids else None


async def log_daily_summary(user: UserConfig, summary: str) -> dict:
    """Find-or-create daily log, then add summary as a comment.

    Pattern:
    1. Search for today's log by title + daily-log tag
    2. If found: add summary as a comment
    3. If not found: create issue, then add summary as a comment
    """
    _check_configured(user)

    # Use PT timezone for date
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%B %-d, %Y")

    existing_id = await find_daily_log(user, today)

    if existing_id:
        # Add comment to existing daily log
        await add_comment(user, existing_id, summary)
        return {
            "action": "comment_added",
            "work_item_id": existing_id,
            "date": today,
            "message": f"Added entry to existing daily log (#{existing_id})",
        }

    # Create new daily log
    item = await create_work_item(
        user=user,
        title=f"Log: {today}",
        description=f"Daily log for {today}",
        area="System",
        priority=4,
        tags="daily-log",
    )

    work_item_id = item["id"]

    # Add the summary as a comment
    await add_comment(user, work_item_id, summary)

    return {
        "action": "created",
        "work_item_id": work_item_id,
        "date": today,
        "message": f"Created daily log #{work_item_id} and added entry",
    }
