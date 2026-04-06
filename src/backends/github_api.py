"""GitHub REST API backend. All file operations go through here."""

import base64
import logging
import time

import httpx

from src.db import UserConfig
from src.exceptions import FileAlreadyExistsError, FileNotFoundError_, GitHubAPIError

logger = logging.getLogger("github")

BASE_URL = "https://api.github.com"
TIMEOUT = 30.0


def _headers(user: UserConfig) -> dict:
    """Build auth headers for GitHub API."""
    return {
        "Authorization": f"token {user.github_pat}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _log_rate_limit(response: httpx.Response, user: UserConfig) -> None:
    """Log GitHub rate limit info from response headers."""
    remaining = response.headers.get("x-ratelimit-remaining")
    if remaining is not None:
        remaining_int = int(remaining)
        if remaining_int <= 500:
            logger.warning(
                f"[{user.name}] GitHub rate limit low: {remaining_int} remaining"
            )


def _repo_url(user: UserConfig) -> str:
    """Build the repo base URL."""
    return f"{BASE_URL}/repos/{user.github_owner}/{user.github_repo}"


async def read_file(user: UserConfig, path: str) -> str:
    """Read a file from the repository. Returns the decoded text content."""
    start = time.time()
    url = f"{_repo_url(user)}/contents/{path}"
    params = {"ref": user.github_branch}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_headers(user), params=params)

    duration_ms = int((time.time() - start) * 1000)
    _log_rate_limit(response, user)

    if response.status_code == 404:
        logger.info(f"[{user.name}] GITHUB read_file {path} -> 404 ({duration_ms}ms)")
        raise FileNotFoundError_(path)

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] GITHUB read_file {path} -> {response.status_code} ({duration_ms}ms)"
        )
        raise GitHubAPIError(response.status_code, response.text, path)

    logger.info(f"[{user.name}] GITHUB read_file {path} -> 200 ({duration_ms}ms)")

    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content


async def read_file_with_sha(user: UserConfig, path: str) -> tuple[str, str]:
    """Read a file and return (content, sha) tuple. SHA needed for updates."""
    start = time.time()
    url = f"{_repo_url(user)}/contents/{path}"
    params = {"ref": user.github_branch}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_headers(user), params=params)

    duration_ms = int((time.time() - start) * 1000)
    _log_rate_limit(response, user)

    if response.status_code == 404:
        logger.info(
            f"[{user.name}] GITHUB read_file_with_sha {path} -> 404 ({duration_ms}ms)"
        )
        raise FileNotFoundError_(path)

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] GITHUB read_file_with_sha {path} "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise GitHubAPIError(response.status_code, response.text, path)

    logger.info(
        f"[{user.name}] GITHUB read_file_with_sha {path} -> 200 ({duration_ms}ms)"
    )

    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


async def write_file(
    user: UserConfig, path: str, content: str, message: str, sha: str | None = None
) -> dict:
    """Write or update a file. If sha is provided, it's an update. Otherwise creates new.

    Returns the commit info from GitHub.
    """
    start = time.time()
    url = f"{_repo_url(user)}/contents/{path}"

    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": user.github_branch,
    }
    if sha:
        body["sha"] = sha

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.put(url, headers=_headers(user), json=body)

    duration_ms = int((time.time() - start) * 1000)
    _log_rate_limit(response, user)

    if response.status_code == 409 and sha:
        # SHA mismatch -- retry once with fresh SHA
        logger.warning(
            f"[{user.name}] GITHUB write_file {path} -> 409 SHA mismatch, retrying"
        )
        _, fresh_sha = await read_file_with_sha(user, path)
        body["sha"] = fresh_sha
        start = time.time()
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.put(url, headers=_headers(user), json=body)
        duration_ms = int((time.time() - start) * 1000)

    if response.status_code == 422:
        logger.error(
            f"[{user.name}] GITHUB write_file {path} -> 422 ({duration_ms}ms)"
        )
        raise GitHubAPIError(422, response.text, path)

    if response.status_code not in (200, 201):
        logger.error(
            f"[{user.name}] GITHUB write_file {path} "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise GitHubAPIError(response.status_code, response.text, path)

    logger.info(
        f"[{user.name}] GITHUB write_file {path} -> {response.status_code} ({duration_ms}ms)"
    )

    return response.json()


async def list_directory(user: UserConfig, path: str = "") -> list[dict]:
    """List contents of a directory. Returns list of {name, path, type, size}."""
    start = time.time()
    url = f"{_repo_url(user)}/contents/{path}" if path else f"{_repo_url(user)}/contents"
    params = {"ref": user.github_branch}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_headers(user), params=params)

    duration_ms = int((time.time() - start) * 1000)
    _log_rate_limit(response, user)

    if response.status_code == 404:
        logger.info(
            f"[{user.name}] GITHUB list_directory {path} -> 404 ({duration_ms}ms)"
        )
        raise FileNotFoundError_(path or "/")

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] GITHUB list_directory {path} "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise GitHubAPIError(response.status_code, response.text, path)

    logger.info(
        f"[{user.name}] GITHUB list_directory {path} -> 200 ({duration_ms}ms)"
    )

    data = response.json()
    if not isinstance(data, list):
        # Path is a file, not a directory
        raise GitHubAPIError(400, f"Path is a file, not a directory: {path}", path)

    return [
        {
            "name": item["name"],
            "path": item["path"],
            "type": item["type"],  # "file" or "dir"
            "size": item.get("size", 0),
        }
        for item in data
    ]


async def delete_file(user: UserConfig, path: str, message: str) -> dict:
    """Delete a file from the repository."""
    # First get the current SHA
    _, sha = await read_file_with_sha(user, path)

    start = time.time()
    url = f"{_repo_url(user)}/contents/{path}"

    body = {
        "message": message,
        "sha": sha,
        "branch": user.github_branch,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(
            "DELETE", url, headers=_headers(user), json=body
        )

    duration_ms = int((time.time() - start) * 1000)
    _log_rate_limit(response, user)

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] GITHUB delete_file {path} "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise GitHubAPIError(response.status_code, response.text, path)

    logger.info(
        f"[{user.name}] GITHUB delete_file {path} -> 200 ({duration_ms}ms)"
    )

    return response.json()


async def get_commits(
    user: UserConfig, count: int = 20, path: str | None = None
) -> list[dict]:
    """Get recent commits. Optionally filtered by path."""
    start = time.time()
    url = f"{_repo_url(user)}/commits"
    params: dict = {"sha": user.github_branch, "per_page": count}
    if path:
        params["path"] = path

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_headers(user), params=params)

    duration_ms = int((time.time() - start) * 1000)
    _log_rate_limit(response, user)

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] GITHUB get_commits -> {response.status_code} ({duration_ms}ms)"
        )
        raise GitHubAPIError(response.status_code, response.text)

    logger.info(
        f"[{user.name}] GITHUB get_commits (count={count}) -> 200 ({duration_ms}ms)"
    )

    data = response.json()
    return [
        {
            "sha": commit["sha"][:7],
            "message": commit["commit"]["message"],
            "author": commit["commit"]["author"]["name"],
            "date": commit["commit"]["author"]["date"],
        }
        for commit in data
    ]


async def file_exists(user: UserConfig, path: str) -> bool:
    """Check if a file exists without raising exceptions."""
    try:
        url = f"{_repo_url(user)}/contents/{path}"
        params = {"ref": user.github_branch}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, headers=_headers(user), params=params)
        return response.status_code == 200
    except Exception:
        return False


async def move_file(
    user: UserConfig, from_path: str, to_path: str, message: str
) -> dict:
    """Move a file (read source -> create at destination -> delete source)."""
    # Read source content and SHA
    content, source_sha = await read_file_with_sha(user, from_path)

    # Create at destination
    await write_file(user, to_path, content, message)

    # Delete source
    start = time.time()
    url = f"{_repo_url(user)}/contents/{from_path}"
    body = {
        "message": f"Delete {from_path} (moved to {to_path})",
        "sha": source_sha,
        "branch": user.github_branch,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(
            "DELETE", url, headers=_headers(user), json=body
        )

    duration_ms = int((time.time() - start) * 1000)

    if response.status_code != 200:
        logger.error(
            f"[{user.name}] GITHUB move_file delete {from_path} "
            f"-> {response.status_code} ({duration_ms}ms)"
        )
        raise GitHubAPIError(response.status_code, response.text, from_path)

    logger.info(
        f"[{user.name}] GITHUB move_file {from_path} -> {to_path} ({duration_ms}ms)"
    )

    return {"from": from_path, "to": to_path, "status": "moved"}
