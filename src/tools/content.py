"""Content tools -- manage project work product (files and documents).

6 tools: list_content, get_document, create_document, update_document,
move_document, delete_document.
"""

import logging

from src.backends import github_api as github
from src.db import UserConfig
from src.exceptions import FileAlreadyExistsError, FileNotFoundError_
from src.validation import validate_path

logger = logging.getLogger("tools.content")


async def list_content(user: UserConfig, path: str = "") -> dict:
    """List contents of a directory."""
    if path:
        path = validate_path(path)

    entries = await github.list_directory(user, path)
    return {
        "path": path or "/",
        "entries": entries,
        "count": len(entries),
    }


async def get_document(user: UserConfig, path: str) -> dict:
    """Read the full contents of a document."""
    path = validate_path(path)
    content = await github.read_file(user, path)
    return {
        "path": path,
        "content": content,
    }


async def create_document(
    user: UserConfig, path: str, content: str, commit_message: str
) -> dict:
    """Create a new document. Fails if file already exists."""
    path = validate_path(path)

    # Check if file already exists
    if await github.file_exists(user, path):
        raise FileAlreadyExistsError(path)

    result = await github.write_file(user, path, content, commit_message)

    return {
        "created": True,
        "path": path,
        "commit": result.get("commit", {}).get("sha", "")[:7],
    }


async def update_document(
    user: UserConfig, path: str, content: str, commit_message: str
) -> dict:
    """Update an existing document. Fails if file doesn't exist."""
    path = validate_path(path)

    # Get current SHA (also verifies file exists)
    _, sha = await github.read_file_with_sha(user, path)

    result = await github.write_file(user, path, content, commit_message, sha=sha)

    return {
        "updated": True,
        "path": path,
        "commit": result.get("commit", {}).get("sha", "")[:7],
    }


async def move_document(
    user: UserConfig, from_path: str, to_path: str, commit_message: str
) -> dict:
    """Move or rename a document."""
    from_path = validate_path(from_path)
    to_path = validate_path(to_path)

    result = await github.move_file(user, from_path, to_path, commit_message)

    return {
        "moved": True,
        "from_path": from_path,
        "to_path": to_path,
    }


async def delete_document(
    user: UserConfig, path: str, commit_message: str
) -> dict:
    """Delete a document."""
    path = validate_path(path)

    await github.delete_file(user, path, commit_message)

    return {
        "deleted": True,
        "path": path,
    }
