"""Tests for identity tools."""

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
    parse_boot_file_references,
)


# -- Fixtures ---------------------------------------------------------------

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


# -- parse_boot_file_references tests ---------------------------------------

def test_parse_boot_refs_single_file():
    md = """## What to Load

### Files (read at boot for this personality)
- `identity/personalities/ops/cascade-checklist.md`

### On demand
- `some/other/file.md`
"""
    refs = parse_boot_file_references(md)
    assert len(refs) == 1
    assert refs[0] == {"path": "identity/personalities/ops/cascade-checklist.md", "type": "file"}


def test_parse_boot_refs_directory():
    md = """## What to Load

### Files (read at boot for this personality)
- Read everything in `cuespan/docs/`
- `cuespan/admin/engagement.md`
- `cuespan/admin/hours.md`

### Wiki
- Some wiki page
"""
    refs = parse_boot_file_references(md)
    assert len(refs) == 3
    assert refs[0] == {"path": "cuespan/docs", "type": "directory"}
    assert refs[1] == {"path": "cuespan/admin/engagement.md", "type": "file"}
    assert refs[2] == {"path": "cuespan/admin/hours.md", "type": "file"}


def test_parse_boot_refs_empty():
    md = """## Something else
No boot files here.
"""
    refs = parse_boot_file_references(md)
    assert refs == []


def test_parse_boot_refs_stops_at_on_demand():
    md = """### Files (read at boot for this personality)
- `boot-file.md`

On demand
- `demand-file.md`
"""
    refs = parse_boot_file_references(md)
    assert len(refs) == 1
    assert refs[0]["path"] == "boot-file.md"


def test_parse_boot_refs_multiple_files():
    md = """### Files (read at boot for this personality)
- `identity/narrative.md`
- `book/BOOK-PLAN.md`
- `book/manuscript/part-3-intent/INTENT-WORKBOOK.md`
"""
    refs = parse_boot_file_references(md)
    assert len(refs) == 3
    assert all(r["type"] == "file" for r in refs)


# -- Identity tool tests (mocked) -------------------------------------------

@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_get_identity_rules(mock_github, user):
    mock_github.read_file = AsyncMock(return_value="# Rules\nRule 1\nRule 2")
    result = await get_identity_rules(user)
    assert "content" in result
    assert "Rule 1" in result["content"]
    mock_github.read_file.assert_called_once_with(user, "identity/identity-rules.md")


@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_get_personalities(mock_github, user):
    mock_github.list_directory = AsyncMock(
        return_value=[
            {"name": "ops", "path": "identity/personalities/ops", "type": "dir", "size": 0},
            {"name": "book", "path": "identity/personalities/book", "type": "dir", "size": 0},
        ]
    )
    mock_github.read_file = AsyncMock(
        side_effect=[
            json.dumps({"name": "Operations", "description": "Ops mode", "trigger_words": ["ops"], "active": True}),
            json.dumps({"name": "Book", "description": "Book mode", "trigger_words": ["book"], "active": True}),
        ]
    )

    result = await get_personalities(user)
    assert len(result["personalities"]) == 2
    assert result["personalities"][0]["name"] == "ops"


@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_detect_mode_match(mock_github, user):
    mock_github.list_directory = AsyncMock(
        return_value=[
            {"name": "ops", "path": "identity/personalities/ops", "type": "dir", "size": 0},
        ]
    )
    mock_github.read_file = AsyncMock(
        return_value=json.dumps({
            "name": "Operations",
            "description": "Ops mode",
            "trigger_words": ["ops", "operations", "system"],
            "active": True,
        })
    )

    result = await detect_mode(user, "Let's work on ops tasks today")
    assert result["mode"] == "ops"
    assert result["confidence"] > 0


@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_detect_mode_no_match(mock_github, user):
    mock_github.list_directory = AsyncMock(return_value=[])
    result = await detect_mode(user, "random unrelated message")
    assert result["mode"] is None
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
@patch("src.tools.identity.github")
async def test_load_context_no_mode(mock_github, user):
    mock_github.list_directory = AsyncMock(return_value=[])
    result = await load_context(user, None)
    assert "available_personalities" in result
