"""Flask 主应用入口。"""

from flask import Flask


def create_app():
    app = Flask(__name__)

    from config.settings import FLASK_SECRET_KEY
    app.config["SECRET_KEY"] = FLASK_SECRET_KEY

    from server.webhook import webhook_bp
    app.register_blueprint(webhook_bp)

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    from config.settings import FLASK_PORT
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=True)
