"""Identity tools -- manage the AI partnership system.

9 tools: load_context, get_identity_rules, update_identity_rules,
get_current_status, get_personalities, get_personality,
update_personality, get_recent_activity, detect_mode.
"""

import json
import logging
import re

from src.backends import azdevops_api as azdevops
from src.backends import github_api as github
from src.db import UserConfig
from src.exceptions import (
    FileNotFoundError_,
    InvalidModeError,
    error_response,
)
from src.validation import validate_mode, validate_path

logger = logging.getLogger("tools.identity")


async def _read_boot_json(user: UserConfig) -> dict:
    """Read identity/boot.json -- the SST for common boot config."""
    content = await github.read_file(user, "identity/boot.json")
    return json.loads(content)


async def _list_active_personalities(user: UserConfig, personality_dir: str = None) -> list[dict]:
    """List all active personalities from the repo."""
    if personality_dir is None:
        try:
            boot = await _read_boot_json(user)
            personality_dir = boot.get("personality_directory", "identity/personalities")
        except (FileNotFoundError_, json.JSONDecodeError):
            personality_dir = "identity/personalities"

    entries = await github.list_directory(user, personality_dir)

    result = []
    for entry in entries:
        if entry["type"] == "dir":
            try:
                pj_content = await github.read_file(
                    user, f"{personality_dir}/{entry['name']}/personality.json"
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
                continue

    return result


async def load_context(user: UserConfig, mode: str | None = None) -> dict:
    """Load the full AI partner context for a conversation.

    All paths come from boot.json and personality.json. No hardcoded paths.
    This mirrors the boot-sequence.md protocol for the MCP path.
    """
    # Step 1: Read boot config
    boot = await _read_boot_json(user)
    personality_dir = boot.get("personality_directory", "identity/personalities")

    if mode is None:
        personalities = await _list_active_personalities(user, personality_dir)
        return {"available_personalities": personalities}

    mode = validate_mode(mode)

    # Step 2: Load common context (from boot.json common_files)
    common_content = {}
    for path in boot.get("common_files", []):
        try:
            content = await github.read_file(user, path)
            common_content[path] = content
        except FileNotFoundError_:
            common_content[path] = f"[File not found: {path}]"

    # Git log (depth from boot.json)
    git_log_depth = boot.get("git_log_depth", 20)
    commits = await github.get_commits(user, count=git_log_depth)

    # Work items (from boot.json work_items config)
    work_items = []
    wi_config = boot.get("work_items", {})
    if wi_config.get("enabled", False) and user.az_org and user.az_project and user.az_pat:
        try:
            work_items = await azdevops.list_work_items(user)
        except Exception as e:
            logger.warning(f"Failed to load work items at boot: {e}")

    # Step 3: Determine personality
    personality_path = f"{personality_dir}/{mode}"
    try:
        personality_json_content = await github.read_file(
            user, f"{personality_path}/personality.json"
        )
    except FileNotFoundError_:
        raise InvalidModeError(mode)

    personality_data = json.loads(personality_json_content)

    # Step 4: Load personality context
    # behavior.md
    try:
        behavior = await github.read_file(user, f"{personality_path}/behavior.md")
    except FileNotFoundError_:
        behavior = "[behavior.md not found]"

    # boot_files from personality.json
    boot_files_content = {}
    for path in personality_data.get("boot_files", []):
        try:
            content = await github.read_file(user, path)
            boot_files_content[path] = content
        except FileNotFoundError_:
            boot_files_content[path] = f"[File not found: {path}]"

    # boot_directories from personality.json
    boot_dir_content = {}
    for dir_path in personality_data.get("boot_directories", []):
        try:
            entries = await github.list_directory(user, dir_path)
            for entry in entries:
                if entry["type"] == "file":
                    try:
                        content = await github.read_file(user, entry["path"])
                        boot_dir_content[entry["path"]] = content
                    except FileNotFoundError_:
                        boot_dir_content[entry["path"]] = f"[File not found: {entry['path']}]"
        except FileNotFoundError_:
            boot_dir_content[dir_path] = f"[Directory not found: {dir_path}]"

    # System awareness
    all_personalities = await _list_active_personalities(user, personality_dir)

    # Step 5: Return everything (resources/wiki as metadata, not content)
    return {
        "common": common_content,
        "recent_activity": commits,
        "work_items": work_items,
        "personality": {
            "metadata": personality_data,
            "behavior_rules": behavior,
        },
        "boot_files": boot_files_content,
        "boot_directory_files": boot_dir_content,
        "resources": personality_data.get("resources", {}),
        "wiki_pages": personality_data.get("wiki_pages", {}),
        "system_awareness": {
            "active_personality": mode,
            "all_personalities": [p["display_name"] for p in all_personalities],
            "total_personalities": len(all_personalities),
            "note": f"You are running the {personality_data.get('name', mode)} personality. "
                    f"There are {len(all_personalities)} active personalities in this system. "
                    f"You do not see other personalities' context. "
                    f"Do not propose system architecture changes -- flag them for Ops.",
        },
    }


async def get_identity_rules(user: UserConfig) -> dict:
    """Get the core identity and behavioral rules."""
    boot = await _read_boot_json(user)
    # identity-rules.md is the first common file by convention
    common_files = boot.get("common_files", ["identity/identity-rules.md"])
    path = common_files[0] if common_files else "identity/identity-rules.md"
    content = await github.read_file(user, path)
    return {"content": content}


async def update_identity_rules(
    user: UserConfig, content: str, change_summary: str
) -> dict:
    """Update the core identity rules."""
    boot = await _read_boot_json(user)
    common_files = boot.get("common_files", ["identity/identity-rules.md"])
    path = common_files[0] if common_files else "identity/identity-rules.md"
    validate_path(path)

    _, sha = await github.read_file_with_sha(user, path)
    result = await github.write_file(user, path, content, change_summary, sha=sha)

    return {
        "updated": True,
        "path": path,
        "commit": result.get("commit", {}).get("sha", "")[:7],
    }


async def get_current_status(user: UserConfig) -> dict:
    """Get the current status (read-only)."""
    boot = await _read_boot_json(user)
    common_files = boot.get("common_files", ["identity/identity-rules.md", "identity/state/status.md"])
    path = common_files[1] if len(common_files) > 1 else "identity/state/status.md"
    content = await github.read_file(user, path)
    return {"content": content}


async def get_personalities(user: UserConfig) -> dict:
    """Get all available personalities."""
    personalities = await _list_active_personalities(user)
    return {"personalities": personalities}


async def get_personality(user: UserConfig, mode: str) -> dict:
    """Get behavioral rules and context for a specific personality."""
    mode = validate_mode(mode)
    boot = await _read_boot_json(user)
    personality_dir = boot.get("personality_directory", "identity/personalities")

    try:
        personality_json_content = await github.read_file(
            user, f"{personality_dir}/{mode}/personality.json"
        )
    except FileNotFoundError_:
        raise InvalidModeError(mode)

    personality_data = json.loads(personality_json_content)

    behavior = await github.read_file(
        user, f"{personality_dir}/{mode}/behavior.md"
    )

    return {
        "metadata": personality_data,
        "behavior_rules": behavior,
    }


async def update_personality(
    user: UserConfig, mode: str, content: str, change_summary: str
) -> dict:
    """Update behavioral rules for a specific personality.

    Only updates behavior.md. personality.json is admin-only.
    """
    mode = validate_mode(mode)
    boot = await _read_boot_json(user)
    personality_dir = boot.get("personality_directory", "identity/personalities")
    path = f"{personality_dir}/{mode}/behavior.md"

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

        score = 0
        for tw in trigger_words:
            tw_words = set(tw.split())
            if tw_words.issubset(message_words):
                score += len(tw_words)
            elif tw in message_lower:
                score += 1

        if score > best_score:
            best_score = score
            best_match = personality

    if best_match and best_score > 0:
        confidence = min(best_score / 3.0, 1.0)
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
