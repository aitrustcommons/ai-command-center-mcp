"""SQLite database for user configuration."""

import logging
import secrets
import sqlite3
from dataclasses import dataclass

from src.config import DB_PATH

logger = logging.getLogger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    api_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    github_owner TEXT NOT NULL,
    github_repo TEXT NOT NULL,
    github_pat TEXT NOT NULL,
    github_branch TEXT NOT NULL DEFAULT 'main',
    az_org TEXT,
    az_project TEXT,
    az_pat TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);
"""


@dataclass
class UserConfig:
    """User configuration loaded from the database."""

    api_key: str
    name: str
    email: str | None
    github_owner: str
    github_repo: str
    github_pat: str
    github_branch: str
    az_org: str | None
    az_project: str | None
    az_pat: str | None
    active: int
    created_at: str


def generate_api_key() -> str:
    """Generate a new API key with aicc- prefix."""
    return f"aicc-{secrets.token_hex(32)}"


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Get a database connection."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str | None = None) -> None:
    """Initialize the database schema."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        logger.info("Database initialized")
    finally:
        conn.close()


def lookup_user(api_key: str, db_path: str | None = None) -> UserConfig | None:
    """Look up a user by API key. Returns None if not found or inactive."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE api_key = ? AND active = 1", (api_key,)
        ).fetchone()
        if row is None:
            return None
        return UserConfig(**dict(row))
    finally:
        conn.close()


def lookup_user_any(api_key: str, db_path: str | None = None) -> UserConfig | None:
    """Look up a user by API key, including inactive users."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE api_key = ?", (api_key,)
        ).fetchone()
        if row is None:
            return None
        return UserConfig(**dict(row))
    finally:
        conn.close()


def add_user(
    name: str,
    github_owner: str,
    github_repo: str,
    github_pat: str,
    email: str | None = None,
    github_branch: str = "main",
    az_org: str | None = None,
    az_project: str | None = None,
    az_pat: str | None = None,
    db_path: str | None = None,
) -> str:
    """Add a new user and return the generated API key."""
    api_key = generate_api_key()
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO users
               (api_key, name, email, github_owner, github_repo, github_pat,
                github_branch, az_org, az_project, az_pat)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                api_key, name, email, github_owner, github_repo, github_pat,
                github_branch, az_org, az_project, az_pat,
            ),
        )
        conn.commit()
        logger.info(f"User added: {name} ({email})")
        return api_key
    finally:
        conn.close()


def list_users(db_path: str | None = None) -> list[dict]:
    """List all users (redacts PATs)."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT api_key, name, email, github_owner, github_repo, "
            "github_branch, az_org, az_project, active, created_at FROM users"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def disable_user(api_key: str, db_path: str | None = None) -> bool:
    """Disable a user by API key. Returns True if found."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "UPDATE users SET active = 0 WHERE api_key = ?", (api_key,)
        )
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"User disabled: {api_key[:12]}...")
            return True
        return False
    finally:
        conn.close()


def enable_user(api_key: str, db_path: str | None = None) -> bool:
    """Re-enable a user by API key. Returns True if found."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "UPDATE users SET active = 1 WHERE api_key = ?", (api_key,)
        )
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"User enabled: {api_key[:12]}...")
            return True
        return False
    finally:
        conn.close()


def rotate_api_key(email: str, db_path: str | None = None) -> str | None:
    """Generate a new API key for a user identified by email. Returns new key or None."""
    new_key = generate_api_key()
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "UPDATE users SET api_key = ? WHERE email = ?", (new_key, email)
        )
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"API key rotated for: {email}")
            return new_key
        return None
    finally:
        conn.close()


def remove_user(api_key: str, db_path: str | None = None) -> bool:
    """Permanently delete a user. Returns True if found."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("DELETE FROM users WHERE api_key = ?", (api_key,))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"User removed: {api_key[:12]}...")
            return True
        return False
    finally:
        conn.close()


def check_health(db_path: str | None = None) -> bool:
    """Check database health. Returns True if healthy."""
    try:
        conn = get_connection(db_path)
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
