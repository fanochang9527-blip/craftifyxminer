"""Core login logic with account lockout and audit trail."""

import logging
from datetime import datetime, timedelta, timezone

from db.connection import fetch_one, get_cursor
from auth.password import verify_password

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def attempt_login(
    username: str,
    password: str,
    ip_address: str = "0.0.0.0",
    user_agent: str = "",
) -> dict:
    """Try to authenticate a user.

    Returns {"ok": bool, "user": dict|None, "error": str}.
    """
    user = fetch_one(
        "SELECT * FROM users WHERE username = %s AND is_active = true",
        (username,),
    )

    if not user:
        _record_attempt(username, ip_address, user_agent, success=False)
        return {"ok": False, "user": None, "error": "用户名或密码错误"}

    if user.get("locked_until") and user["locked_until"] > _utcnow():
        remaining = (user["locked_until"] - _utcnow()).seconds // 60 + 1
        _record_attempt(username, ip_address, user_agent, success=False)
        return {"ok": False, "user": None, "error": f"账号已锁定，请 {remaining} 分钟后重试"}

    if not verify_password(password, user["password_hash"]):
        new_fails = (user.get("failed_attempts") or 0) + 1
        updates = {"failed_attempts": new_fails}
        if new_fails >= MAX_FAILED_ATTEMPTS:
            updates["locked_until"] = _utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            logger.warning("Account locked: %s (IP: %s)", username, ip_address)

        with get_cursor() as cur:
            cur.execute(
                "UPDATE users SET failed_attempts = %s, locked_until = %s WHERE id = %s",
                (updates["failed_attempts"], updates.get("locked_until"), user["id"]),
            )
        _record_attempt(username, ip_address, user_agent, success=False)

        remaining_attempts = MAX_FAILED_ATTEMPTS - new_fails
        if remaining_attempts > 0:
            return {"ok": False, "user": None, "error": f"用户名或密码错误（还剩 {remaining_attempts} 次尝试）"}
        return {"ok": False, "user": None, "error": f"账号已锁定，请 {LOCKOUT_MINUTES} 分钟后重试"}

    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = %s WHERE id = %s",
            (_utcnow(), user["id"]),
        )
    _record_attempt(username, ip_address, user_agent, success=True)

    safe_user = dict(user)
    safe_user.pop("password_hash", None)
    return {"ok": True, "user": safe_user, "error": ""}


def _record_attempt(username: str, ip: str, ua: str, *, success: bool) -> None:
    try:
        with get_cursor() as cur:
            cur.execute(
                "INSERT INTO login_attempts (username, ip_address, success, user_agent) VALUES (%s, %s, %s, %s)",
                (username, ip or None, success, ua[:500] if ua else None),
            )
    except Exception:
        logger.debug("Failed to record login attempt", exc_info=True)
