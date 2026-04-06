"""Work item tools -- manage work tracking (backed by Azure DevOps).

7 tools: get_tracking_areas, list_work_items, get_work_item,
create_work_item, update_work_item, add_comment, log_daily_summary.
"""

import json
import logging

from src.backends import azdevops_api as azdevops
from src.backends import github_api as github
from src.db import UserConfig
from src.exceptions import AzDevOpsNotConfiguredError, FileNotFoundError_
from src.validation import validate_priority, validate_work_item_id

logger = logging.getLogger("tools.work_items")


async def get_tracking_areas(user: UserConfig) -> dict:
    """Get all valid work areas from personalities and tracking/areas.json.

    Merges area_path from each personality.json with entries from
    tracking/areas.json. Deduplicates by area name.
    """
    areas = {}

    # 1. Read area_path from each personality.json
    try:
        personalities_dir = "identity/personalities"
        entries = await github.list_directory(user, personalities_dir)

        for entry in entries:
            if entry["type"] == "dir":
                try:
                    pj_content = await github.read_file(
                        user,
                        f"{personalities_dir}/{entry['name']}/personality.json",
                    )
                    data = json.loads(pj_content)
                    area_path = data.get("area_path")
                    if area_path:
                        areas[area_path] = {
                            "area": area_path,
                            "full_path": f"{user.az_project}\\{area_path}"
                            if user.az_project
                            else area_path,
                            "source": f"personality:{entry['name']}",
                            "personality": entry["name"],
                        }
                except (FileNotFoundError_, json.JSONDecodeError):
                    continue
    except FileNotFoundError_:
        logger.warning("identity/personalities directory not found")

    # 2. Read tracking/areas.json
    try:
        areas_content = await github.read_file(user, "identity/tracking/areas.json")
        areas_data = json.loads(areas_content)

        for area_entry in areas_data:
            area_name = area_entry.get("area_path") or area_entry.get("name", "")
            if area_name and area_name not in areas:
                areas[area_name] = {
                    "area": area_name,
                    "full_path": f"{user.az_project}\\{area_name}"
                    if user.az_project
                    else area_name,
                    "source": "tracking/areas.json",
                    "personality": area_entry.get("personality"),
                }
    except (FileNotFoundError_, json.JSONDecodeError):
        logger.info("tracking/areas.json not found or invalid")

    return {
        "areas": list(areas.values()),
        "count": len(areas),
    }


async def list_work_items_tool(
    user: UserConfig,
    area: str | None = None,
    state: str | None = None,
    priority: int | None = None,
    tags: str | None = None,
) -> dict:
    """List work items with optional filters."""
    if priority is not None:
        validate_priority(priority)

    items = await azdevops.list_work_items(
        user, area=area, state=state, priority=priority, tags=tags
    )

    return {
        "items": items,
        "count": len(items),
        "filters": {
            "area": area,
            "state": state,
            "priority": priority,
            "tags": tags,
        },
    }


async def get_work_item_tool(user: UserConfig, work_item_id: int) -> dict:
    """Get full details of a specific work item."""
    work_item_id = validate_work_item_id(work_item_id)

    item = await azdevops.get_work_item(user, work_item_id)

    fields = item.get("fields", {})
    comments = []
    if "System.CommentCount" in fields and fields["System.CommentCount"] > 0:
        # Comments come with $expand=all
        comment_data = item.get("comments", {})
        if isinstance(comment_data, dict):
            for c in comment_data.get("comments", []):
                comments.append(
                    {
                        "id": c.get("id"),
                        "text": c.get("text", ""),
                        "created_by": c.get("createdBy", {}).get(
                            "displayName", ""
                        ),
                        "created_date": c.get("createdDate", ""),
                    }
                )

    return {
        "id": item["id"],
        "title": fields.get("System.Title", ""),
        "state": fields.get("System.State", ""),
        "priority": fields.get("Microsoft.VSTS.Common.Priority", 0),
        "area": fields.get("System.AreaPath", ""),
        "description": fields.get("System.Description", ""),
        "tags": fields.get("System.Tags", ""),
        "type": fields.get("System.WorkItemType", ""),
        "created_date": fields.get("System.CreatedDate", ""),
        "changed_date": fields.get("System.ChangedDate", ""),
        "comments": comments,
    }


async def create_work_item_tool(
    user: UserConfig,
    title: str,
    description: str,
    area: str,
    priority: int = 3,
    tags: str | None = None,
) -> dict:
    """Create a new work item."""
    validate_priority(priority)

    item = await azdevops.create_work_item(
        user,
        title=title,
        description=description,
        area=area,
        priority=priority,
        tags=tags,
    )

    return {
        "created": True,
        "id": item["id"],
        "title": title,
        "area": area,
        "url": item.get("_links", {}).get("html", {}).get("href", ""),
    }


async def update_work_item_tool(
    user: UserConfig, work_item_id: int, changes: dict
) -> dict:
    """Update a work item's fields."""
    work_item_id = validate_work_item_id(work_item_id)

    if "priority" in changes:
        validate_priority(changes["priority"])

    item = await azdevops.update_work_item(user, work_item_id, changes)

    return {
        "updated": True,
        "id": work_item_id,
        "changes": list(changes.keys()),
    }


async def add_comment_tool(user: UserConfig, work_item_id: int, text: str) -> dict:
    """Add a comment to a work item."""
    work_item_id = validate_work_item_id(work_item_id)

    result = await azdevops.add_comment(user, work_item_id, text)

    return {
        "added": True,
        "work_item_id": work_item_id,
        "comment_id": result.get("id"),
    }


async def log_daily_summary_tool(user: UserConfig, summary: str) -> dict:
    """Log a daily summary using the find-or-create pattern."""
    result = await azdevops.log_daily_summary(user, summary)
    return result
