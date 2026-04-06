"""Tests for work item tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.db import UserConfig
from src.exceptions import AzDevOpsNotConfiguredError
from src.tools.work_items import (
    add_comment_tool,
    create_work_item_tool,
    get_tracking_areas,
    get_work_item_tool,
    list_work_items_tool,
    log_daily_summary_tool,
    update_work_item_tool,
)


@pytest.fixture
def user():
    return UserConfig(
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
        active=1,
        created_at="2026-01-01",
    )


@pytest.fixture
def user_no_az():
    return UserConfig(
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


def test_validate_priority():
    from src.validation import validate_priority

    assert validate_priority(1) == 1
    assert validate_priority(4) == 4
    assert validate_priority(None) is None

    with pytest.raises(ValueError):
        validate_priority(0)

    with pytest.raises(ValueError):
        validate_priority(5)
