"""Password hashing (bcrypt cost=12) and complexity validation."""

import re

import bcrypt

BCRYPT_ROUNDS = 12
MIN_LENGTH = 8
_COMPLEXITY_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).+$")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def validate_complexity(plain: str) -> str | None:
    """Return an error message if password is too weak, else None."""
    if len(plain) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters"
    if not _COMPLEXITY_RE.match(plain):
        return "Password must contain both letters and digits"
    return None
