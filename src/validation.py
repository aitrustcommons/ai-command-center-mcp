"""Input validation helpers. Reject dangerous paths and invalid inputs."""

import re


def validate_path(path: str) -> str:
    """Validate and normalize a file path. Raises ValueError on invalid input."""
    if not path:
        raise ValueError("Path cannot be empty")

    # Reject absolute paths
    if path.startswith("/"):
        raise ValueError("Absolute paths are not allowed")

    # Reject directory traversal
    if ".." in path.split("/"):
        raise ValueError("Path traversal (..) is not allowed")

    # Reject .git paths
    if path == ".git" or path.startswith(".git/"):
        raise ValueError("Access to .git is not allowed")

    # Normalize: strip leading/trailing slashes and whitespace
    path = path.strip().strip("/")

    return path


def validate_mode(mode: str) -> str:
    """Validate a personality mode name. Alphanumeric + hyphens only."""
    if not mode:
        raise ValueError("Mode cannot be empty")

    if not re.match(r"^[a-zA-Z0-9-]+$", mode):
        raise ValueError(
            "Mode must contain only alphanumeric characters and hyphens"
        )

    return mode.lower()


def validate_work_item_id(work_item_id: int | str) -> int:
    """Validate a work item ID is a positive integer."""
    try:
        wid = int(work_item_id)
    except (TypeError, ValueError):
        raise ValueError("Work item ID must be an integer")

    if wid <= 0:
        raise ValueError("Work item ID must be positive")

    return wid


def validate_priority(priority: int | None) -> int | None:
    """Validate priority is 1-4 or None."""
    if priority is None:
        return None
    if not isinstance(priority, int) or priority < 1 or priority > 4:
        raise ValueError("Priority must be 1 (critical), 2 (high), 3 (medium), or 4 (low)")
    return priority
