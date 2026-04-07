"""SQLite database for user configuration.

The website (theintentlayer.com) owns the users table schema. This module
creates it only if it doesn't exist (for standalone testing / CLI use).
In production, the shared database is already initialized by the website.
"""

import logging
import secrets
import sqlite3
from dataclasses import dataclass

from src.config import DB_PATH

logger = logging.getLogger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    google_id TEXT UNIQUE,
    github_id TEXT UNIQUE,
    github_owner TEXT,
    github_repo TEXT,
    github_pat TEXT,
    github_branch TEXT DEFAULT 'main',
    az_org TEXT,
    az_project TEXT,
    az_pat TEXT,
    api_key TEXT UNIQUE NOT NULL,
    setup_complete INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);
CREATE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id);
"""


@dataclass
class UserConfig:
    """User configuration loaded from the database."""

    id: int
    name: str
    email: str
    api_key: str
    github_owner: str | None
    github_repo: str | None
    github_pat: str | None
    github_branch: str
    az_org: str | None
    az_project: str | None
    az_pat: str | None
    setup_complete: int
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
    """Initialize the database schema (creates table only if it doesn't exist)."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        logger.info("Database initialized")
    finally:
        conn.close()


def _row_to_config(row: sqlite3.Row) -> UserConfig:
    """Convert a database row to a UserConfig dataclass."""
    return UserConfig(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        api_key=row["api_key"],
        github_owner=row["github_owner"],
        github_repo=row["github_repo"],
        github_pat=row["github_pat"],
        github_branch=row["github_branch"] or "main",
        az_org=row["az_org"],
        az_project=row["az_project"],
        az_pat=row["az_pat"],
        setup_complete=row["setup_complete"],
        active=row["active"],
        created_at=row["created_at"],
    )


def lookup_user(api_key: str, db_path: str | None = None) -> UserConfig | None:
    """Look up a user by API key. Returns None if not found, inactive, or setup incomplete."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE api_key = ? AND active = 1 AND setup_complete = 1",
            (api_key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_config(row)
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
        return _row_to_config(row)
    finally:
        conn.close()


def lookup_user_by_id(user_id: int, db_path: str | None = None) -> UserConfig | None:
    """Look up a user by ID. Returns None if not found, inactive, or setup incomplete.

    Used by JWT auth: the website's OAuth flow puts user.id in the JWT sub claim.
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND active = 1 AND setup_complete = 1",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_config(row)
    finally:
        conn.close()


def add_user(
    name: str,
    email: str,
    github_owner: str,
    github_repo: str,
    github_pat: str,
    github_branch: str = "main",
    az_org: str | None = None,
    az_project: str | None = None,
    az_pat: str | None = None,
    db_path: str | None = None,
) -> str:
    """Add a new user via CLI (emergency fallback). Returns the generated API key.

    Creates a full user row with password_hash=None and setup_complete=1.
    """
    api_key = generate_api_key()
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO users
               (name, email, api_key, github_owner, github_repo, github_pat,
                github_branch, az_org, az_project, az_pat, setup_complete)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                name, email, api_key, github_owner, github_repo, github_pat,
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
            "SELECT id, api_key, name, email, github_owner, github_repo, "
            "github_branch, az_org, az_project, active, setup_complete, created_at FROM users"
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
