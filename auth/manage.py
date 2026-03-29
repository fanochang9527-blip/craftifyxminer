"""CLI tool for user management.

Usage:
    python -m auth.manage create-admin --username admin --password <pwd>
    python -m auth.manage create-user  --username bd1 --password <pwd> --role bd
    python -m auth.manage reset-password --username admin --password <new>
    python -m auth.manage unlock --username admin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config.settings  # noqa: F401, E402

from auth.password import hash_password, validate_complexity  # noqa: E402
from db.connection import fetch_one, get_cursor  # noqa: E402


def create_user(username: str, password: str, role: str = "bd", display_name: str = "") -> None:
    err = validate_complexity(password)
    if err:
        print(f"ERROR: {err}")
        sys.exit(1)

    existing = fetch_one("SELECT id FROM users WHERE username = %s", (username,))
    if existing:
        print(f"User '{username}' already exists (id={existing['id']}), skipping.")
        return

    pw_hash = hash_password(password)
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, display_name, role) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, pw_hash, display_name or username, role),
        )
        row = cur.fetchone()
    print(f"Created user '{username}' (id={row['id']}, role={role})")


def reset_password(username: str, password: str) -> None:
    err = validate_complexity(password)
    if err:
        print(f"ERROR: {err}")
        sys.exit(1)

    pw_hash = hash_password(password)
    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s, password_changed_at = NOW(), failed_attempts = 0, locked_until = NULL WHERE username = %s RETURNING id",
            (pw_hash, username),
        )
        row = cur.fetchone()
    if not row:
        print(f"User '{username}' not found")
        sys.exit(1)
    print(f"Password reset for '{username}'")


def unlock_user(username: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username = %s RETURNING id",
            (username,),
        )
        row = cur.fetchone()
    if not row:
        print(f"User '{username}' not found")
        sys.exit(1)
    print(f"Unlocked user '{username}'")


def main() -> None:
    parser = argparse.ArgumentParser(description="User management CLI")
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create-admin")
    p_create.add_argument("--username", required=True)
    p_create.add_argument("--password", required=True)
    p_create.add_argument("--display-name", default="")

    p_user = sub.add_parser("create-user")
    p_user.add_argument("--username", required=True)
    p_user.add_argument("--password", required=True)
    p_user.add_argument("--role", default="bd", choices=["admin", "bd"])
    p_user.add_argument("--display-name", default="")

    p_reset = sub.add_parser("reset-password")
    p_reset.add_argument("--username", required=True)
    p_reset.add_argument("--password", required=True)

    p_unlock = sub.add_parser("unlock")
    p_unlock.add_argument("--username", required=True)

    args = parser.parse_args()

    if args.command == "create-admin":
        create_user(args.username, args.password, role="admin", display_name=args.display_name)
    elif args.command == "create-user":
        create_user(args.username, args.password, role=args.role, display_name=args.display_name)
    elif args.command == "reset-password":
        reset_password(args.username, args.password)
    elif args.command == "unlock":
        unlock_user(args.username)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
