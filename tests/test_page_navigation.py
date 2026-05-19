"""Tests for BD review workbench page navigation jump feature."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock streamlit before importing dashboard modules
mock_st = MagicMock()
mock_st.session_state = {}
sys.modules["streamlit"] = mock_st

import yaml


class TestJumpI18n:
    """Verify the 'jump' translation key exists in both locale files."""

    def test_zh_locale_has_jump_key(self):
        path = Path(__file__).resolve().parent.parent / "dashboard" / "locales" / "zh.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["candidates"]["jump"] == "跳转"

    def test_en_locale_has_jump_key(self):
        path = Path(__file__).resolve().parent.parent / "dashboard" / "locales" / "en.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["candidates"]["jump"] == "Go"


class TestCandidatesPageSource:
    """Verify jump controls are present in the candidates page source."""

    def test_jump_controls_present(self):
        path = Path(__file__).resolve().parent.parent / "dashboard" / "pages" / "2_candidates.py"
        source = path.read_text(encoding="utf-8")
        assert "jump_page" in source
        assert "jump_input_" in source
        assert "jump_btn_" in source
        assert "st.number_input" in source
        assert 'label_visibility="collapsed"' in source
