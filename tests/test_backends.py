"""Tests for backend modules."""

import pytest
from src.backends.azdevops_api import _convert_newlines, _full_area_path
from src.db import UserConfig
from src.validation import validate_mode


@pytest.fixture
def user():
    return UserConfig(
        id=1,
        api_key="aicc-test",
        name="Test User",
        email="test@example.com",
        github_owner="testowner",
        github_repo="testrepo",
        github_pat="ghp_test",
        github_branch="main",
        az_org="testorg",
        az_project="The Big Push",
        az_pat="azpat_test",
        setup_complete=1,
        active=1,
        created_at="2026-01-01",
    )


# -- AZ DevOps helpers -------------------------------------------------------

def test_convert_newlines():
    """Verify \n -> <br> conversion for AZ DevOps text fields."""
    assert _convert_newlines("line 1\nline 2") == "line 1<br>line 2"
    assert _convert_newlines("no newlines") == "no newlines"
    assert _convert_newlines("a\nb\nc") == "a<br>b<br>c"
    assert _convert_newlines("") == ""


def test_full_area_path(user):
    """Verify area path prefixing with project name."""
    assert _full_area_path(user, "CueSpan") == "The Big Push\\CueSpan"
    assert (
        _full_area_path(user, "AI-Trust-Commons\\OmniSynth")
        == "The Big Push\\AI-Trust-Commons\\OmniSynth"
    )
    assert _full_area_path(user, "System") == "The Big Push\\System"


# -- Validation ---------------------------------------------------------------

def test_validate_mode_valid():
    assert validate_mode("ops") == "ops"
    assert validate_mode("ai-trust-commons") == "ai-trust-commons"
    assert validate_mode("CueSpan") == "cuespan"


def test_validate_mode_invalid():
    with pytest.raises(ValueError):
        validate_mode("")

    with pytest.raises(ValueError):
        validate_mode("ops/../../etc")

    with pytest.raises(ValueError):
        validate_mode("ops; rm -rf /")


# -- Database -----------------------------------------------------------------

def test_db_init_and_crud(tmp_path):
    """Test database CRUD operations."""
    from src import db

    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    # Add user
    api_key = db.add_user(
        name="Test",
        github_owner="owner",
        github_repo="repo",
        github_pat="ghp_test",
        email="test@test.com",
        db_path=db_path,
    )
    assert api_key.startswith("aicc-")
    assert len(api_key) == 69  # "aicc-" + 64 hex chars

    # List users
    users = db.list_users(db_path)
    assert len(users) == 1
    assert users[0]["name"] == "Test"

    # Lookup active user
    user = db.lookup_user(api_key, db_path)
    assert user is not None
    assert user.name == "Test"

    # Disable
    assert db.disable_user(api_key, db_path) is True
    assert db.lookup_user(api_key, db_path) is None  # Inactive not returned

    # Enable
    assert db.enable_user(api_key, db_path) is True
    assert db.lookup_user(api_key, db_path) is not None

    # Rotate
    new_key = db.rotate_api_key("test@test.com", db_path)
    assert new_key is not None
    assert new_key != api_key
    assert db.lookup_user(api_key, db_path) is None  # Old key invalid
    assert db.lookup_user(new_key, db_path) is not None

    # Remove
    assert db.remove_user(new_key, db_path) is True
    assert db.list_users(db_path) == []


def test_db_health(tmp_path):
    """Test database health check."""
    from src import db

    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    assert db.check_health(db_path) is True
