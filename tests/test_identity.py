"""Tests for identity tools (V5.0 -- boot.json based, no prose parsing)."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.db import UserConfig
from src.tools.identity import (
    detect_mode,
    get_identity_rules,
    get_personalities,
    get_personality,
    load_context,
)


# -- Fixtures ---------------------------------------------------------------

BOOT_JSON = json.dumps({
    "version": "5.0",
    "common_files": [
        "identity/identity-rules.md",
        "identity/state/status.md"
    ],
    "personality_directory": "identity/personalities",
    "default_personality": "ops",
    "git_log_depth": 20,
    "work_items": {
        "enabled": True,
        "script": "system/scripts/az_ops.py",
        "pat_file": "~/azure-dev-ops-claude-token.txt"
    }
})

OPS_PERSONALITY_JSON = json.dumps({
    "name": "Ops",
    "description": "General operations",
    "area_path": "System",
    "folder": None,
    "trigger_words": ["ops", "system"],
    "git_identity": {"name": "Claude-Ops", "email": "claude-ops@test.dev"},
    "boot_files": ["identity/personalities/ops/cascade-checklist.md"],
    "boot_directories": [],
    "resources": {"linkedin": {"paths": ["linkedin/"], "description": "Campaign data"}},
    "wiki_pages": {"subscriptions": "Active-Subscriptions"},
    "active": True,
    "created": "2026-03-30"
})

BOOK_PERSONALITY_JSON = json.dumps({
    "name": "Book",
    "description": "Book writing",
    "trigger_words": ["book", "chapter"],
    "boot_files": [],
    "boot_directories": [],
    "resources": {},
    "wiki_pages": {},
    "active": True,
})


@pytest.fixture
def user():
    return UserConfig(
        id=1,
        name="Test User",
        email="test@example.com",
        api_key="aicc-test",
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


# -- load_context tests (boot.json based) -----------------------------------

@pytest.mark.asyncio
@patch("src.tools.identity.azdevops")
@patch("src.tools.identity.github")
async def test_load_context_no_mode(mock_github, mock_azdevops, user):
    mock_github.read_file = AsyncMock(return_value=BOOT_JSON)
    mock_github.list_directory = AsyncMock(return_value=[])
    result = await load_context(user, None)
    assert "available_personalities" in result


@pytest.mark.asyncio
@patch("src.tools.identity.azdevops")
@patch("src.tools.identity.github")
async def test_load_context_reads_from_boot_json(mock_github, mock_azdevops, user):
    """Verify load_context reads common_files from boot.json, not hardcoded."""
    call_count = {"n": 0}
    paths_read = []

    async def mock_read(u, path):
        paths_read.append(path)
        if path == "identity/boot.json":
            return BOOT_JSON
        if path.endswith("personality.json"):
            return OPS_PERSONALITY_JSON
        if path.endswith("behavior.md"):
            return "# Ops behavior"
        return f"content of {path}"

    mock_github.read_file = AsyncMock(side_effect=mock_read)
    mock_github.list_directory = AsyncMock(return_value=[
        {"name": "ops", "path": "identity/personalities/ops", "type": "dir", "size": 0},
    ])
    mock_github.get_commits = AsyncMock(return_value=[])
    mock_azdevops.list_work_items = AsyncMock(return_value=[])

    result = await load_context(user, "ops")

    # boot.json should be the first file read
    assert paths_read[0] == "identity/boot.json"
    # common_files from boot.json should be read
    assert "identity/identity-rules.md" in paths_read
    assert "identity/state/status.md" in paths_read
    # boot_files from personality.json should be read
    assert "identity/personalities/ops/cascade-checklist.md" in paths_read
    # Response should have common, not old "identity_rules" key
    assert "common" in result
    assert "resources" in result
    assert "wiki_pages" in result


@pytest.mark.asyncio
@patch("src.tools.identity.azdevops")
@patch("src.tools.identity.github")
async def test_load_context_includes_resources_as_metadata(mock_github, mock_azdevops, user):
    """Resources and wiki_pages should be in response as metadata, not loaded content."""
    async def mock_read(u, path):
        if path == "identity/boot.json":
            return BOOT_JSON
        if path.endswith("personality.json"):
            return OPS_PERSONALITY_JSON
        if path.endswith("behavior.md"):
            return "# Ops behavior"
        return f"content of {path}"

    mock_github.read_file = AsyncMock(side_effect=mock_read)
    mock_github.list_directory = AsyncMock(return_value=[
        {"name": "ops", "path": "identity/personalities/ops", "type": "dir", "size": 0},
    ])
    mock_github.get_commits = AsyncMock(return_value=[])
    mock_azdevops.list_work_items = AsyncMock(return_value=[])

    result = await load_context(user, "ops")

    assert "linkedin" in result["resources"]
    assert result["resources"]["linkedin"]["description"] == "Campaign data"
    assert "subscriptions" in result["wiki_pages"]


# -- get_identity_rules tests -----------------------------------------------

@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_get_identity_rules(mock_github, user):
    async def mock_read(u, path):
        if path == "identity/boot.json":
            return BOOT_JSON
        return "# Rules\nRule 1\nRule 2"

    mock_github.read_file = AsyncMock(side_effect=mock_read)
    result = await get_identity_rules(user)
    assert "content" in result
    assert "Rule 1" in result["content"]


# -- get_personalities tests ------------------------------------------------

@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_get_personalities(mock_github, user):
    async def mock_read(u, path):
        if path == "identity/boot.json":
            return BOOT_JSON
        if "ops" in path:
            return OPS_PERSONALITY_JSON
        if "book" in path:
            return BOOK_PERSONALITY_JSON
        return "{}"

    mock_github.read_file = AsyncMock(side_effect=mock_read)
    mock_github.list_directory = AsyncMock(
        return_value=[
            {"name": "ops", "path": "identity/personalities/ops", "type": "dir", "size": 0},
            {"name": "book", "path": "identity/personalities/book", "type": "dir", "size": 0},
        ]
    )

    result = await get_personalities(user)
    assert len(result["personalities"]) == 2


# -- detect_mode tests ------------------------------------------------------

@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_detect_mode_match(mock_github, user):
    async def mock_read(u, path):
        if path == "identity/boot.json":
            return BOOT_JSON
        return OPS_PERSONALITY_JSON

    mock_github.read_file = AsyncMock(side_effect=mock_read)
    mock_github.list_directory = AsyncMock(
        return_value=[
            {"name": "ops", "path": "identity/personalities/ops", "type": "dir", "size": 0},
        ]
    )

    result = await detect_mode(user, "Let's work on ops tasks today")
    assert result["mode"] == "ops"
    assert result["confidence"] > 0


@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_detect_mode_no_match(mock_github, user):
    async def mock_read(u, path):
        if path == "identity/boot.json":
            return BOOT_JSON
        return OPS_PERSONALITY_JSON

    mock_github.read_file = AsyncMock(side_effect=mock_read)
    mock_github.list_directory = AsyncMock(return_value=[])
    result = await detect_mode(user, "random unrelated message")
    assert result["mode"] is None
    assert result["confidence"] == 0.0
