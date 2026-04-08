"""Tests for work item tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.db import UserConfig
from src.exceptions import AzDevOpsNotConfiguredError
from src.tools.work_items import (
    add_comment_tool,
    attach_file_tool,
    cascade_tool,
    close_work_item_tool,
    create_work_item_tool,
    daily_logs_tool,
    edit_comment_tool,
    get_tracking_areas,
    get_work_item_tool,
    list_attachments_tool,
    list_work_items_tool,
    log_daily_summary_tool,
    reopen_work_item_tool,
    search_work_items_tool,
    update_work_item_tool,
)


@pytest.fixture
def user():
    return UserConfig(
        id=1,
        api_key="aicc-test",
        name="Test User",
        email="test@example.com",
        github_owner="testowner",
        github_repo="testrepo",
        github_pat="ghp_test",
        github_branch="main",
        az_org="testorg",
        az_project="TestProject",
        az_pat="azpat_test",
        setup_complete=1,
        active=1,
        created_at="2026-01-01",
    )


@pytest.fixture
def user_no_az():
    return UserConfig(
        id=1,
        api_key="aicc-test",
        name="Test User",
        email="test@example.com",
        github_owner="testowner",
        github_repo="testrepo",
        github_pat="ghp_test",
        github_branch="main",
        az_org=None,
        az_project=None,
        az_pat=None,
        setup_complete=1,
        active=1,
        created_at="2026-01-01",
    )


@pytest.mark.asyncio
@patch("src.tools.work_items.github")
async def test_get_tracking_areas(mock_github, user):
    mock_github.list_directory = AsyncMock(
        return_value=[
            {"name": "ops", "path": "identity/personalities/ops", "type": "dir", "size": 0},
        ]
    )
    mock_github.read_file = AsyncMock(
        side_effect=[
            # personality.json
            json.dumps({"name": "Ops", "area_path": "System"}),
            # tracking/areas.json
            json.dumps([{"area_path": "Career", "name": "Career"}]),
        ]
    )

    result = await get_tracking_areas(user)
    assert result["count"] == 2
    areas = {a["area"] for a in result["areas"]}
    assert "System" in areas
    assert "Career" in areas


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_list_work_items(mock_azdevops, user):
    mock_azdevops.list_work_items = AsyncMock(
        return_value=[
            {"id": 1, "title": "Test Item", "state": "Active", "priority": 2, "area": "System", "tags": "", "type": "Issue"},
        ]
    )
    result = await list_work_items_tool(user)
    assert result["count"] == 1
    assert result["items"][0]["title"] == "Test Item"


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_create_work_item(mock_azdevops, user):
    mock_azdevops.create_work_item = AsyncMock(
        return_value={"id": 42, "_links": {"html": {"href": "https://example.com/42"}}}
    )
    result = await create_work_item_tool(
        user, title="New Item", description="Desc", area="System"
    )
    assert result["created"] is True
    assert result["id"] == 42


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_add_comment(mock_azdevops, user):
    mock_azdevops.add_comment = AsyncMock(return_value={"id": 99})
    result = await add_comment_tool(user, 42, "A comment")
    assert result["added"] is True
    assert result["comment_id"] == 99


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_log_daily_summary(mock_azdevops, user):
    mock_azdevops.log_daily_summary = AsyncMock(
        return_value={
            "action": "created",
            "work_item_id": 100,
            "date": "April 6, 2026",
            "message": "Created daily log #100 and added entry",
        }
    )
    result = await log_daily_summary_tool(user, "Today we built the MCP server.")
    assert result["action"] == "created"


def test_validate_work_item_id():
    from src.validation import validate_work_item_id

    assert validate_work_item_id(42) == 42
    assert validate_work_item_id("42") == 42

    with pytest.raises(ValueError):
        validate_work_item_id(-1)

    with pytest.raises(ValueError):
        validate_work_item_id("abc")


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_close_work_item(mock_azdevops, user):
    mock_azdevops.update_work_item = AsyncMock(return_value={"id": 42})
    result = await close_work_item_tool(user, 42)
    assert result["closed"] is True
    assert result["state"] == "Done"
    mock_azdevops.update_work_item.assert_called_once_with(
        user, 42, {"state": "Done"}
    )


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_reopen_work_item(mock_azdevops, user):
    mock_azdevops.update_work_item = AsyncMock(return_value={"id": 42})
    result = await reopen_work_item_tool(user, 42)
    assert result["reopened"] is True
    assert result["state"] == "To Do"
    mock_azdevops.update_work_item.assert_called_once_with(
        user, 42, {"state": "To Do"}
    )


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_search_work_items(mock_azdevops, user):
    mock_azdevops.search_work_items = AsyncMock(
        return_value=[
            {"id": 1, "title": "MCP server", "state": "Active", "priority": 2, "area": "System", "tags": "", "type": "Issue"},
        ]
    )
    result = await search_work_items_tool(user, "MCP")
    assert result["count"] == 1
    assert result["query"] == "MCP"


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_attach_file(mock_azdevops, user):
    mock_azdevops.attach_file = AsyncMock(
        return_value={
            "work_item_id": 42,
            "filename": "notes.txt",
            "attachment_url": "https://example.com/att/1",
        }
    )
    result = await attach_file_tool(user, 42, "notes.txt", "some content")
    assert result["attached"] is True
    assert result["filename"] == "notes.txt"


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_list_attachments(mock_azdevops, user):
    mock_azdevops.list_attachments = AsyncMock(
        return_value=[
            {"url": "https://example.com/att/1", "filename": "notes.txt", "comment": "", "added_date": ""},
        ]
    )
    result = await list_attachments_tool(user, 42)
    assert result["count"] == 1
    assert result["attachments"][0]["filename"] == "notes.txt"


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_edit_comment(mock_azdevops, user):
    mock_azdevops.edit_comment = AsyncMock(return_value={"id": 99})
    result = await edit_comment_tool(user, 42, 99, "Updated comment")
    assert result["edited"] is True
    assert result["comment_id"] == 99


@pytest.mark.asyncio
@patch("src.tools.work_items.github")
@patch("src.tools.work_items.azdevops")
async def test_cascade_article(mock_azdevops, mock_github, user):
    mock_github.read_file = AsyncMock(
        return_value=(
            "# Cascade Checklists\n\n"
            "## When a new article publishes\n\n"
            "- [ ] Blog post\n"
            "- [ ] Medium import\n"
            "- [ ] Zenodo upload\n\n"
            "## When a LinkedIn post goes live\n\n"
            "- [ ] Save post text\n"
        )
    )
    mock_azdevops.create_work_item = AsyncMock(
        return_value={"id": 100, "_links": {"html": {"href": "https://example.com/100"}}}
    )
    result = await cascade_tool(user, "article", "Publish Article 6")
    assert result["created"] is True
    assert result["cascade_type"] == "article"
    assert result["area"] == "AI-Trust-Commons"
    # Verify the description includes the checklist steps
    call_args = mock_azdevops.create_work_item.call_args
    assert "Blog post" in call_args.kwargs["description"]


@pytest.mark.asyncio
async def test_cascade_invalid_type(user):
    with pytest.raises(ValueError, match="Unknown cascade type"):
        await cascade_tool(user, "invalid", "Test")


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_daily_logs(mock_azdevops, user):
    mock_azdevops.get_daily_logs = AsyncMock(
        return_value=[
            {
                "id": 268,
                "title": "Log: April 8, 2026",
                "state": "To Do",
                "created_date": "2026-04-08",
                "comments": [{"id": 1, "text": "Built MCP tools", "created_by": "Claude", "created_date": "2026-04-08"}],
            }
        ]
    )
    result = await daily_logs_tool(user, 7)
    assert result["count"] == 1
    assert result["days"] == 7
    assert result["logs"][0]["title"] == "Log: April 8, 2026"


@pytest.mark.asyncio
@patch("src.tools.work_items.azdevops")
async def test_get_work_item_includes_attachments(mock_azdevops, user):
    mock_azdevops.get_work_item = AsyncMock(
        return_value={
            "id": 42,
            "fields": {
                "System.Title": "Test",
                "System.State": "Active",
                "Microsoft.VSTS.Common.Priority": 2,
                "System.AreaPath": "TestProject\\System",
                "System.Description": "Desc",
                "System.Tags": "",
                "System.WorkItemType": "Issue",
                "System.CreatedDate": "2026-04-08",
                "System.ChangedDate": "2026-04-08",
                "System.CommentCount": 0,
            },
            "relations": [
                {
                    "rel": "AttachedFile",
                    "url": "https://example.com/att/1",
                    "attributes": {"name": "notes.txt", "comment": "Attached: notes.txt", "resourceCreatedDate": "2026-04-08"},
                }
            ],
        }
    )
    result = await get_work_item_tool(user, 42)
    assert len(result["attachments"]) == 1
    assert result["attachments"][0]["filename"] == "notes.txt"


def test_validate_priority():
    from src.validation import validate_priority

    assert validate_priority(1) == 1
    assert validate_priority(4) == 4
    assert validate_priority(None) is None

    with pytest.raises(ValueError):
        validate_priority(0)

    with pytest.raises(ValueError):
        validate_priority(5)
