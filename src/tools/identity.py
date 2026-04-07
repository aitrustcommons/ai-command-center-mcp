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


def parse_boot_file_references(behavior_md: str) -> list[dict]:
    """Extract file paths from the boot files section of behavior-rules-and-context.md.

    Looks for boot file references and stops at on-demand/wiki/never-read sections.
    Handles the inconsistent formatting across different personality files.

    Returns list of {"path": str, "type": "file"|"directory"}.

    NOTE: This is a band-aid parser. V5.0 will move boot file lists to a
    structured JSON config, eliminating the need to parse prose. See
    system/docs/versions/v50-proposed-design.md.
    """
    results = []
    lines = behavior_md.split("\n")
    in_boot_section = False
    boot_lines = []

    # Stop words: if any of these appear in a line (case-insensitive, ignoring
    # markdown bold markers), we've left the boot section. Covers all known
    # personality file variations.
    STOP_PATTERNS = [
        "on demand",
        "on-demand",
        "wiki page",
        "wiki pages",
        "never read",
        "do not read at boot",
    ]

    for line in lines:
        stripped = line.strip()
        # Remove markdown bold markers for matching
        stripped_clean = stripped.replace("**", "").replace("*", "").lower()

        # Start triggers: various ways personalities declare boot files
        if not in_boot_section:
            if re.search(r"read at boot", stripped_clean):
                in_boot_section = True
                # CueSpan style: "At boot, read everything in `cuespan/docs/`."
                # The trigger line itself may contain a path
                backtick_paths = re.findall(r"`([^`]+)`", line)
                for path in backtick_paths:
                    path = path.strip()
                    if path:
                        if path.endswith("/"):
                            results.append({"path": path.rstrip("/"), "type": "directory"})
                        else:
                            results.append({"path": path, "type": "file"})
                continue
            # CueSpan also has "Also read at boot:"
            if re.search(r"also read at boot", stripped_clean):
                in_boot_section = True
                continue
            continue

        # We're in the boot section. Check stop conditions.

        # Stop at section headers (## or ###)
        if re.match(r"^#{1,3}\s", stripped):
            break

        # Stop at any stop pattern (handles bold, plain, with or without colons)
        if any(pattern in stripped_clean for pattern in STOP_PATTERNS):
            break

        # Stop at a new bold subsection that isn't about boot files
        # e.g., "**Wiki pages (clone and check):**"
        if stripped_clean.startswith(("wiki", "on demand", "on-demand", "never")):
            break

        boot_lines.append(line)

    # Extract backtick-quoted paths from boot lines only
    for line in boot_lines:
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

    # Recent activity (git log equivalent)
    commits = await github.get_commits(user, count=20)

    # Work items list (CLAUDE.md step 1.4: az_ops.py list)
    work_items = []
    if user.az_org and user.az_project and user.az_pat:
        try:
            work_items = await azdevops.list_work_items(user)
        except Exception as e:
            logger.warning(f"Failed to load work items at boot: {e}")

    # System awareness: all active personalities so the model knows it's one of N
    all_personalities = await _list_active_personalities(user)

    return {
        "identity_rules": identity_rules,
        "current_status": status,
        "personality": {
            "metadata": personality_data,
            "behavior_rules": behavior,
        },
        "boot_files": boot_context,
        "recent_activity": commits,
        "work_items": work_items,
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
