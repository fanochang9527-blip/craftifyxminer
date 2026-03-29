"""Flask request decorators for JWT-based authentication."""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timezone

import jwt
from flask import current_app, jsonify, request

from db.connection import fetch_one

logger = logging.getLogger(__name__)


def _decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])
        user = fetch_one("SELECT * FROM users WHERE id = %s AND is_active = true", (payload["sub"],))
        if not user:
            return None
        pwd_changed = user.get("password_changed_at")
        if pwd_changed:
            issued = datetime.fromtimestamp(payload.get("iat", 0), tz=timezone.utc)
            if pwd_changed.tzinfo is None:
                pwd_changed = pwd_changed.replace(tzinfo=timezone.utc)
            if issued < pwd_changed:
                return None
        safe = dict(user)
        safe.pop("password_hash", None)
        return safe
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        user = _decode_token(auth_header[7:])
        if not user:
            return jsonify({"error": "Invalid or expired token"}), 401
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        user = _decode_token(auth_header[7:])
        if not user:
            return jsonify({"error": "Invalid or expired token"}), 401
        if user.get("role") != "admin":
            return jsonify({"error": "Admin privileges required"}), 403
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper
