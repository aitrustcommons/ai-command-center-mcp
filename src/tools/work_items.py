"""Work item tools -- manage work tracking (backed by Azure DevOps).

15 tools: get_tracking_areas, list_work_items, get_work_item,
create_work_item, update_work_item, add_comment, log_daily_summary,
close_work_item, reopen_work_item, search_work_items, attach_file,
list_attachments, edit_comment, cascade, daily_logs.
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
    """Get full details of a work item including comments and attachments."""
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

    # Extract attachments from relations
    attachments = []
    relations = item.get("relations", []) or []
    for rel in relations:
        if rel.get("rel") == "AttachedFile":
            attrs = rel.get("attributes", {})
            attachments.append({
                "url": rel.get("url", ""),
                "filename": attrs.get("name", attrs.get("comment", "")),
                "comment": attrs.get("comment", ""),
                "added_date": attrs.get("resourceCreatedDate", ""),
            })

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
        "attachments": attachments,
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


async def close_work_item_tool(user: UserConfig, work_item_id: int) -> dict:
    """Close a work item by transitioning to Done."""
    work_item_id = validate_work_item_id(work_item_id)

    item = await azdevops.update_work_item(
        user, work_item_id, {"state": "Done"}
    )

    return {
        "closed": True,
        "id": work_item_id,
        "state": "Done",
    }


async def reopen_work_item_tool(user: UserConfig, work_item_id: int) -> dict:
    """Reopen a work item by transitioning back to To Do."""
    work_item_id = validate_work_item_id(work_item_id)

    item = await azdevops.update_work_item(
        user, work_item_id, {"state": "To Do"}
    )

    return {
        "reopened": True,
        "id": work_item_id,
        "state": "To Do",
    }


async def search_work_items_tool(user: UserConfig, query: str) -> dict:
    """Search work items by keyword across title and description."""
    items = await azdevops.search_work_items(user, query)

    return {
        "items": items,
        "count": len(items),
        "query": query,
    }


async def attach_file_tool(
    user: UserConfig, work_item_id: int, filename: str, content: str
) -> dict:
    """Attach a file to a work item."""
    work_item_id = validate_work_item_id(work_item_id)

    result = await azdevops.attach_file(user, work_item_id, filename, content)

    return {
        "attached": True,
        "work_item_id": work_item_id,
        "filename": filename,
        "attachment_url": result["attachment_url"],
    }


async def list_attachments_tool(user: UserConfig, work_item_id: int) -> dict:
    """List attachments on a work item."""
    work_item_id = validate_work_item_id(work_item_id)

    attachments = await azdevops.list_attachments(user, work_item_id)

    return {
        "work_item_id": work_item_id,
        "attachments": attachments,
        "count": len(attachments),
    }


async def edit_comment_tool(
    user: UserConfig, work_item_id: int, comment_id: int, text: str
) -> dict:
    """Edit an existing comment on a work item."""
    work_item_id = validate_work_item_id(work_item_id)

    result = await azdevops.edit_comment(user, work_item_id, comment_id, text)

    return {
        "edited": True,
        "work_item_id": work_item_id,
        "comment_id": comment_id,
    }


async def cascade_tool(user: UserConfig, cascade_type: str, title: str) -> dict:
    """Create a cascade work item from cascade-checklist.md.

    Reads the checklist via GitHub API, extracts the relevant section,
    and creates a work item with checkbox steps embedded in the description.
    """
    # Type map: cascade type -> section header in checklist
    type_map = {
        "article": "When a new article publishes",
        "book": "When a book chapter locks",
        "linkedin": "When a LinkedIn post goes live",
        "narrative": "When narrative identity updates",
        "product": "When a product ships or updates",
        "workstream": "When a new workstream starts",
        "session-close": "When a session closes",
        "resume": "When resume updates",
        "zenodo": "When Zenodo deposit is created",
    }

    section_name = type_map.get(cascade_type.lower())
    if not section_name:
        raise ValueError(
            f"Unknown cascade type '{cascade_type}'. "
            f"Valid types: {', '.join(sorted(type_map.keys()))}"
        )

    # Read cascade-checklist.md via GitHub API
    checklist_path = "identity/personalities/ops/cascade-checklist.md"
    try:
        content = await github.read_file(user, checklist_path)
    except FileNotFoundError_:
        raise ValueError(
            f"Cascade checklist not found at {checklist_path}"
        )

    # Extract the relevant section
    lines = content.split("\n")
    section_lines = []
    in_section = False
    for line in lines:
        if line.startswith("## "):
            if in_section:
                break
            if section_name.lower() in line.lower():
                in_section = True
                continue
        elif in_section:
            section_lines.append(line)

    if not section_lines:
        raise ValueError(
            f"Section '{section_name}' not found in cascade checklist"
        )

    steps = "\n".join(section_lines).strip()
    description = f"## Cascade: {section_name}\n\n{steps}"

    # Area map: cascade type -> default area
    area_map = {
        "article": "AI-Trust-Commons",
        "book": "Book",
        "linkedin": "LinkedIn",
        "narrative": "System",
        "product": "Products",
        "workstream": "System",
        "session-close": "System",
        "resume": "Career",
        "zenodo": "AI-Trust-Commons",
    }
    area = area_map.get(cascade_type.lower(), "System")

    item = await azdevops.create_work_item(
        user=user,
        title=title,
        description=description,
        area=area,
        priority=1,
        tags="cascade",
    )

    return {
        "created": True,
        "id": item["id"],
        "title": title,
        "cascade_type": cascade_type,
        "area": area,
        "url": item.get("_links", {}).get("html", {}).get("href", ""),
    }


async def daily_logs_tool(user: UserConfig, days: int = 7) -> dict:
    """Show recent daily log entries with their comments."""
    logs = await azdevops.get_daily_logs(user, days)

    return {
        "logs": logs,
        "count": len(logs),
        "days": days,
    }
