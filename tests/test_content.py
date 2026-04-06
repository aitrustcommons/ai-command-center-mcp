"""Tests for content tools."""

import pytest
from unittest.mock import AsyncMock, patch

from src.db import UserConfig
from src.exceptions import FileAlreadyExistsError, FileNotFoundError_
from src.tools.content import (
    create_document,
    delete_document,
    get_document,
    list_content,
    move_document,
    update_document,
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
        az_org=None,
        az_project=None,
        az_pat=None,
        active=1,
        created_at="2026-01-01",
    )


@pytest.mark.asyncio
@patch("src.tools.content.github")
async def test_list_content_root(mock_github, user):
    mock_github.list_directory = AsyncMock(
        return_value=[
            {"name": "README.md", "path": "README.md", "type": "file", "size": 100},
            {"name": "src", "path": "src", "type": "dir", "size": 0},
        ]
    )
    result = await list_content(user, "")
    assert result["count"] == 2
    assert result["path"] == "/"


@pytest.mark.asyncio
@patch("src.tools.content.github")
async def test_get_document(mock_github, user):
    mock_github.read_file = AsyncMock(return_value="# Hello\nWorld")
    result = await get_document(user, "docs/hello.md")
    assert result["content"] == "# Hello\nWorld"
    assert result["path"] == "docs/hello.md"


@pytest.mark.asyncio
@patch("src.tools.content.github")
async def test_create_document_new(mock_github, user):
    mock_github.file_exists = AsyncMock(return_value=False)
    mock_github.write_file = AsyncMock(
        return_value={"commit": {"sha": "abc1234567890"}}
    )
    result = await create_document(user, "docs/new.md", "content", "create file")
    assert result["created"] is True


@pytest.mark.asyncio
@patch("src.tools.content.github")
async def test_create_document_exists(mock_github, user):
    mock_github.file_exists = AsyncMock(return_value=True)
    with pytest.raises(FileAlreadyExistsError):
        await create_document(user, "docs/existing.md", "content", "create")


@pytest.mark.asyncio
@patch("src.tools.content.github")
async def test_update_document(mock_github, user):
    mock_github.read_file_with_sha = AsyncMock(return_value=("old content", "sha123"))
    mock_github.write_file = AsyncMock(
        return_value={"commit": {"sha": "def4567890123"}}
    )
    result = await update_document(user, "docs/file.md", "new content", "update")
    assert result["updated"] is True


@pytest.mark.asyncio
@patch("src.tools.content.github")
async def test_delete_document(mock_github, user):
    mock_github.delete_file = AsyncMock(return_value={})
    result = await delete_document(user, "docs/old.md", "remove old file")
    assert result["deleted"] is True


@pytest.mark.asyncio
@patch("src.tools.content.github")
async def test_move_document(mock_github, user):
    mock_github.move_file = AsyncMock(
        return_value={"from": "a.md", "to": "b.md", "status": "moved"}
    )
    result = await move_document(user, "a.md", "b.md", "rename")
    assert result["moved"] is True


def test_validate_path_rejects_traversal():
    from src.validation import validate_path

    with pytest.raises(ValueError, match="traversal"):
        validate_path("../etc/passwd")

    with pytest.raises(ValueError, match="traversal"):
        validate_path("foo/../../bar")


def test_validate_path_rejects_git():
    from src.validation import validate_path

    with pytest.raises(ValueError, match=".git"):
        validate_path(".git/config")


def test_validate_path_rejects_absolute():
    from src.validation import validate_path

    with pytest.raises(ValueError, match="Absolute"):
        validate_path("/etc/passwd")
