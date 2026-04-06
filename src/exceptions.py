"""Backend-specific exceptions and error codes."""


class AuthError(Exception):
    """Invalid or missing API key."""
    pass


class UserDisabledError(Exception):
    """User exists but is disabled."""
    pass


class GitHubAPIError(Exception):
    """GitHub API returned an unexpected error."""

    def __init__(self, status_code: int, message: str, path: str | None = None):
        self.status_code = status_code
        self.message = message
        self.path = path
        super().__init__(message)


class AzDevOpsAPIError(Exception):
    """Azure DevOps API returned an unexpected error."""

    def __init__(
        self, status_code: int, message: str, work_item_id: int | None = None
    ):
        self.status_code = status_code
        self.message = message
        self.work_item_id = work_item_id
        super().__init__(message)


class AzDevOpsNotConfiguredError(Exception):
    """User has no Azure DevOps credentials configured."""
    pass


class FileNotFoundError_(Exception):
    """File or path not found in the repository."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"File not found: {path}")


class FileAlreadyExistsError(Exception):
    """File already exists at the given path."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"File already exists: {path}")


class InvalidModeError(Exception):
    """Personality mode not found."""

    def __init__(self, mode: str):
        self.mode = mode
        super().__init__(f"Personality mode not found: {mode}")


def error_response(code: str, message: str, details: dict | None = None) -> dict:
    """Build a structured error response for MCP tool results."""
    result = {"error": True, "code": code, "message": message}
    if details:
        result["details"] = details
    return result
