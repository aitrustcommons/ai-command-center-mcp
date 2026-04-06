"""Identity tools -- manage the AI partnership system.

9 tools: load_context, get_identity_rules, update_identity_rules,
get_current_status, get_personalities, get_personality,
update_personality, get_recent_activity, detect_mode.
"""

import json
import logging
import re

from src.backends import github_api as github
from src.db import UserConfig
from src.exceptions import (
    FileNotFoundError_,
    InvalidModeError,
    error_response,
)
from src.validation import validate_mode, validate_path

logger = logging.getLogger("tools.identity")


def parse_boot_file_references(behavior_md: str) -> list[dict]:
    """Extract file paths from the boot files section of behavior-rules-and-context.md.

    Returns list of {"path": str, "type": "file"|"directory"}.
    """
    results = []

    # Find the boot files section (case-insensitive)
    lines = behavior_md.split("\n")
    in_boot_section = False
    boot_lines = []

    for line in lines:
        # Start of boot files section
        if re.search(r"files\s*\(read at boot", line, re.IGNORECASE):
            in_boot_section = True
            continue

        if in_boot_section:
            # Stop at next section header or "on demand" / "wiki" subsection
            stripped = line.strip().lower()
            if stripped.startswith("##"):
                break
            if stripped.startswith("on demand") or stripped.startswith("wiki"):
                break
            if re.match(r"^#+\s", line):
                break

            boot_lines.append(line)

    # Extract backtick-quoted paths from bullet points
    for line in boot_lines:
        # Match: - `path/to/file.md` or - `path/to/dir/`
        # Also match: "read everything in `path/`"
        backtick_paths = re.findall(r"`([^`]+)`", line)
        for path in backtick_paths:
            path = path.strip()
            if not path:
                continue

            # Determine if file or directory
            if path.endswith("/"):
                results.append({"path": path.rstrip("/"), "type": "directory"})
            else:
                results.append({"path": path, "type": "file"})

    return results


async def _list_active_personalities(user: UserConfig) -> list[dict]:
    """List all active personalities from the repo."""
    personalities_dir = "identity/personalities"
    entries = await github.list_directory(user, personalities_dir)

    result = []
    for entry in entries:
        if entry["type"] == "dir":
            try:
                pj_content = await github.read_file(
                    user, f"{personalities_dir}/{entry['name']}/personality.json"
                )
                data = json.loads(pj_content)
                if data.get("active", True):
                    result.append(
                        {
                            "name": entry["name"],
                            "display_name": data.get("name", entry["name"]),
                            "description": data.get("description", ""),
                            "trigger_words": data.get("trigger_words", []),
                        }
                    )
            except (FileNotFoundError_, json.JSONDecodeError):
                # Skip directories without valid personality.json
                continue

    return result


async def load_context(user: UserConfig, mode: str | None = None) -> dict:
    """Load the full AI partner context for a conversation."""
    if mode is None:
        # Return list of available personalities
        personalities = await _list_active_personalities(user)
        return {"available_personalities": personalities}

    mode = validate_mode(mode)

    # Check personality exists
    try:
        personality_json = await github.read_file(
            user, f"identity/personalities/{mode}/personality.json"
        )
    except FileNotFoundError_:
        raise InvalidModeError(mode)

    personality_data = json.loads(personality_json)

    # Load all boot context in parallel-ish (sequential for now, but each is fast)
    identity_rules = await github.read_file(user, "identity/identity-rules.md")
    status = await github.read_file(user, "identity/state/status.md")
    behavior = await github.read_file(
        user, f"identity/personalities/{mode}/behavior-rules-and-context.md"
    )

    # Parse behavior file for boot-referenced files
    boot_refs = parse_boot_file_references(behavior)
    boot_context = {}

    for ref in boot_refs:
        try:
            if ref["type"] == "directory":
                # List directory and read all files
                entries = await github.list_directory(user, ref["path"])
                for entry in entries:
                    if entry["type"] == "file":
                        try:
                            content = await github.read_file(
                                user, entry["path"]
                            )
                            boot_context[entry["path"]] = content
                        except FileNotFoundError_:
                            boot_context[entry["path"]] = (
                                f"[File not found: {entry['path']}]"
                            )
            else:
                content = await github.read_file(user, ref["path"])
                boot_context[ref["path"]] = content
        except FileNotFoundError_:
            boot_context[ref["path"]] = f"[File not found: {ref['path']}]"

    # Recent activity
    commits = await github.get_commits(user, count=20)

    return {
        "identity_rules": identity_rules,
        "current_status": status,
        "personality": {
            "metadata": personality_data,
            "behavior_rules": behavior,
        },
        "boot_files": boot_context,
        "recent_activity": commits,
    }


async def get_identity_rules(user: UserConfig) -> dict:
    """Get the core identity and behavioral rules."""
    content = await github.read_file(user, "identity/identity-rules.md")
    return {"content": content}


async def update_identity_rules(
    user: UserConfig, content: str, change_summary: str
) -> dict:
    """Update the core identity rules."""
    validate_path("identity/identity-rules.md")

    # Get current SHA for update
    _, sha = await github.read_file_with_sha(user, "identity/identity-rules.md")
    result = await github.write_file(
        user, "identity/identity-rules.md", content, change_summary, sha=sha
    )

    return {
        "updated": True,
        "path": "identity/identity-rules.md",
        "commit": result.get("commit", {}).get("sha", "")[:7],
    }


async def get_current_status(user: UserConfig) -> dict:
    """Get the current status (read-only)."""
    content = await github.read_file(user, "identity/state/status.md")
    return {"content": content}


async def get_personalities(user: UserConfig) -> dict:
    """Get all available personalities."""
    personalities = await _list_active_personalities(user)
    return {"personalities": personalities}


async def get_personality(user: UserConfig, mode: str) -> dict:
    """Get behavioral rules and context for a specific personality."""
    mode = validate_mode(mode)

    try:
        personality_json = await github.read_file(
            user, f"identity/personalities/{mode}/personality.json"
        )
    except FileNotFoundError_:
        raise InvalidModeError(mode)

    personality_data = json.loads(personality_json)

    behavior = await github.read_file(
        user, f"identity/personalities/{mode}/behavior-rules-and-context.md"
    )

    return {
        "metadata": personality_data,
        "behavior_rules": behavior,
    }


async def update_personality(
    user: UserConfig, mode: str, content: str, change_summary: str
) -> dict:
    """Update behavioral rules for a specific personality.

    Only updates behavior-rules-and-context.md. personality.json is admin-only.
    """
    mode = validate_mode(mode)
    path = f"identity/personalities/{mode}/behavior-rules-and-context.md"

    # Verify personality exists
    try:
        _, sha = await github.read_file_with_sha(user, path)
    except FileNotFoundError_:
        raise InvalidModeError(mode)

    result = await github.write_file(user, path, content, change_summary, sha=sha)

    return {
        "updated": True,
        "path": path,
        "commit": result.get("commit", {}).get("sha", "")[:7],
    }


async def get_recent_activity(user: UserConfig, count: int = 20) -> dict:
    """Get recent commits."""
    commits = await github.get_commits(user, count=count)
    return {"commits": commits, "count": len(commits)}


async def detect_mode(user: UserConfig, message: str) -> dict:
    """Detect personality mode from a message using trigger word matching."""
    personalities = await _list_active_personalities(user)

    message_lower = message.lower()
    message_words = set(re.findall(r"\w+", message_lower))

    best_match = None
    best_score = 0

    for personality in personalities:
        trigger_words = [tw.lower() for tw in personality.get("trigger_words", [])]
        if not trigger_words:
            continue

        # Count how many trigger words appear in the message
        score = 0
        for tw in trigger_words:
            tw_words = set(tw.split())
            if tw_words.issubset(message_words):
                score += len(tw_words)  # Multi-word triggers score higher
            elif tw in message_lower:
                score += 1

        if score > best_score:
            best_score = score
            best_match = personality

    if best_match and best_score > 0:
        confidence = min(best_score / 3.0, 1.0)  # Normalize to 0-1
        return {
            "mode": best_match["name"],
            "display_name": best_match["display_name"],
            "confidence": round(confidence, 2),
            "matched_from": "trigger_words",
        }

    return {
        "mode": None,
        "display_name": None,
        "confidence": 0.0,
        "message": "No personality matched. Use get_personalities() to see available options.",
    }
