"""Tests for /health response including model file status."""

import sys
from unittest.mock import MagicMock

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()


def test_health_includes_model_status(monkeypatch, tmp_path):
    import config.settings as settings
    from server.app import create_app

    sps = tmp_path / "sps_model.joblib"
    sell = tmp_path / "sellability_model.joblib"
    sps.write_text("x")

    monkeypatch.setattr(settings, "MODEL_PATH", sps)
    monkeypatch.setattr(settings, "SELLABILITY_MODEL_PATH", sell)

    app = create_app()
    c = app.test_client()
    r = c.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    assert data["models"]["sps_model"]["exists"] is True
    assert data["models"]["sellability_model"]["exists"] is False
