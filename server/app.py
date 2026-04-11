"""Flask 主应用入口。"""

import logging
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

import jwt
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
_file_handler = RotatingFileHandler(os.path.join(_LOG_DIR, "flask.log"), maxBytes=10 * 1024 * 1024, backupCount=5)
_file_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger().addHandler(_file_handler)
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)

    from config.settings import FLASK_SECRET_KEY, JWT_SECRET_KEY, JWT_EXPIRY_HOURS
    app.config["SECRET_KEY"] = FLASK_SECRET_KEY
    app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
    app.config["JWT_EXPIRY_HOURS"] = JWT_EXPIRY_HOURS

    def _get_real_ip():
        return request.headers.get("X-Real-IP", get_remote_address())

    limiter = Limiter(key_func=_get_real_ip, app=app, default_limits=["60/minute"], storage_uri="memory://")

    from server.webhook import webhook_bp
    from server.api import api_bp

    app.register_blueprint(webhook_bp)
    app.register_blueprint(api_bp)

    @app.route("/health")
    def health():
        from config.settings import MODEL_PATH, SELLABILITY_MODEL_PATH

        return {
            "status": "ok",
            "models": {
                "sps_model": {"path": str(MODEL_PATH), "exists": MODEL_PATH.exists()},
                "sellability_model": {
                    "path": str(SELLABILITY_MODEL_PATH),
                    "exists": SELLABILITY_MODEL_PATH.exists(),
                },
            },
        }

    @app.route("/api/login", methods=["POST"])
    @limiter.limit("5/minute")
    def api_login():
        data = request.get_json(silent=True) or {}
        username = data.get("username", "")
        password = data.get("password", "")
        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400

        from auth.login import attempt_login
        ip = request.headers.get("X-Real-IP", request.remote_addr)
        ua = request.headers.get("User-Agent", "")
        result = attempt_login(username, password, ip_address=ip, user_agent=ua)
        if not result["ok"]:
            return jsonify({"error": result["error"]}), 401

        user = result["user"]
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user["id"]),
            "role": user["role"],
            "iat": now,
            "exp": now + timedelta(hours=app.config["JWT_EXPIRY_HOURS"]),
        }
        token = jwt.encode(payload, app.config["JWT_SECRET_KEY"], algorithm="HS256")
        return jsonify({"token": token, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}})

    @app.errorhandler(Exception)
    def handle_exception(e):
        logger.exception("Unhandled exception")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    return app


app = create_app()

if __name__ == "__main__":
    from config.settings import FLASK_PORT
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=True)
