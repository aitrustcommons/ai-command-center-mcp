"""Admin CLI for managing users and the database.

Usage:
    python -m src.admin.cli init
    python -m src.admin.cli add --name "Nikhil" --email nikhil@example.com --github-owner nikhilsi ...
    python -m src.admin.cli list
    python -m src.admin.cli disable --key aicc-xxx
    python -m src.admin.cli enable --key aicc-xxx
    python -m src.admin.cli rotate --email nikhil@example.com
    python -m src.admin.cli remove --key aicc-xxx
"""

import argparse
import sys

from src import db


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize the database."""
    db.init_db(args.db)
    print("Database initialized.")


def cmd_add(args: argparse.Namespace) -> None:
    """Add a new user (emergency fallback -- primary path is the website)."""
    db.init_db(args.db)  # Ensure schema exists
    api_key = db.add_user(
        name=args.name,
        email=args.email,
        github_owner=args.github_owner,
        github_repo=args.github_repo,
        github_pat=args.github_pat,
        github_branch=args.github_branch or "main",
        az_org=args.az_org,
        az_project=args.az_project,
        az_pat=args.az_pat,
        db_path=args.db,
    )
    print(f"User added: {args.name}")
    print(f"API key generated: {api_key}")
    print("Give this key to the user for their MCP connector.")


def cmd_list(args: argparse.Namespace) -> None:
    """List all users."""
    users = db.list_users(args.db)
    if not users:
        print("No users found.")
        return

    for user in users:
        status = "active" if user["active"] else "DISABLED"
        setup = "ready" if user["setup_complete"] else "pending"
        az_info = f", az={user['az_org']}/{user['az_project']}" if user["az_org"] else ""
        gh_info = f"{user['github_owner']}/{user['github_repo']}" if user["github_owner"] else "no repo"
        print(
            f"  [{status}/{setup}] {user['name']} ({user['email']}) "
            f"-- {gh_info}"
            f"{az_info}"
            f" -- key={user['api_key'][:16]}..."
            f" -- created={user['created_at']}"
        )


def cmd_disable(args: argparse.Namespace) -> None:
    """Disable a user."""
    if db.disable_user(args.key, args.db):
        print(f"User disabled: {args.key[:16]}...")
    else:
        print("User not found.")
        sys.exit(1)


def cmd_enable(args: argparse.Namespace) -> None:
    """Re-enable a user."""
    if db.enable_user(args.key, args.db):
        print(f"User enabled: {args.key[:16]}...")
    else:
        print("User not found.")
        sys.exit(1)


def cmd_rotate(args: argparse.Namespace) -> None:
    """Rotate a user's API key."""
    new_key = db.rotate_api_key(args.email, args.db)
    if new_key:
        print(f"New API key: {new_key}")
    else:
        print(f"No user found with email: {args.email}")
        sys.exit(1)


def cmd_remove(args: argparse.Namespace) -> None:
    """Permanently delete a user."""
    if db.remove_user(args.key, args.db):
        print(f"User permanently removed: {args.key[:16]}...")
    else:
        print("User not found.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aicc-admin",
        description="AiCC MCP Server -- Admin CLI",
    )
    parser.add_argument(
        "--db", default=None,
        help="Database path (overrides AICC_DB_PATH)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="Initialize the database")

    # add
    add_p = sub.add_parser("add", help="Add a new user (emergency fallback)")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--email", required=True)
    add_p.add_argument("--github-owner", required=True)
    add_p.add_argument("--github-repo", required=True)
    add_p.add_argument("--github-pat", required=True)
    add_p.add_argument("--github-branch", default="main")
    add_p.add_argument("--az-org", default=None)
    add_p.add_argument("--az-project", default=None)
    add_p.add_argument("--az-pat", default=None)

    # list
    sub.add_parser("list", help="List all users")

    # disable
    dis_p = sub.add_parser("disable", help="Disable a user")
    dis_p.add_argument("--key", required=True)

    # enable
    en_p = sub.add_parser("enable", help="Re-enable a user")
    en_p.add_argument("--key", required=True)

    # rotate
    rot_p = sub.add_parser("rotate", help="Rotate a user's API key")
    rot_p.add_argument("--email", required=True)

    # remove
    rem_p = sub.add_parser("remove", help="Permanently delete a user")
    rem_p.add_argument("--key", required=True)

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "add": cmd_add,
        "list": cmd_list,
        "disable": cmd_disable,
        "enable": cmd_enable,
        "rotate": cmd_rotate,
        "remove": cmd_remove,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
