"""Server configuration from environment variables."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Server settings
PORT: int = int(os.getenv("AICC_PORT", "8443"))
DB_PATH: str = os.getenv("AICC_DB_PATH", "./aicc.db")
LOG_LEVEL: str = os.getenv("AICC_LOG_LEVEL", "info").upper()
LOG_DIR: str = os.getenv("AICC_LOG_DIR", "./logs")
VERSION: str = "1.0.1"

# Default user API key -- used when no Authorization header is provided.
# Set this to a valid API key to allow claude.ai connectors (which don't
# send API keys) to use the server. Leave empty to require auth on all requests.
DEFAULT_USER_KEY: str = os.getenv("AICC_DEFAULT_USER_KEY", "")

# Ensure log directory exists
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    """Configure structured logging with file rotation and stdout."""
    from logging.handlers import TimedRotatingFileHandler

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Stdout handler (for docker logs)
    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    # File handler with daily rotation (7 days retained)
    log_file = Path(LOG_DIR) / "aicc-mcp.log"
    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def validate_config() -> None:
    """Validate configuration on startup. Fail fast with clear errors."""
    logger = logging.getLogger("config")

    # Check DB path is writable
    db_dir = Path(DB_PATH).parent
    if not db_dir.exists():
        db_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created database directory: {db_dir}")

    # Check port is valid
    if not (1 <= PORT <= 65535):
        raise ValueError(f"AICC_PORT must be 1-65535, got {PORT}")

    # Check log directory is writable
    log_dir = Path(LOG_DIR)
    if not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Config validated: port={PORT}, db={DB_PATH}, log_level={LOG_LEVEL}")
