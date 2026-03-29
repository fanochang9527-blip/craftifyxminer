"""Lightweight i18n for Streamlit dashboard — YAML-based locale files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
import streamlit as st

_LOCALES_DIR = Path(__file__).parent / "locales"
_SUPPORTED = ("zh", "en")
_DEFAULT = "zh"


@lru_cache(maxsize=4)
def _load_locale(lang: str) -> dict:
    path = _LOCALES_DIR / f"{lang}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_lang() -> str:
    return st.session_state.get("lang", _DEFAULT)


def t(key: str, **kwargs) -> str:
    """Translate *key* (dot-separated path) using current locale.

    Example: t("candidates.title") -> "候选人浏览与 BD 判定"
    Supports {name} placeholders via **kwargs.
    """
    data = _load_locale(get_lang())
    parts = key.split(".")
    node = data
    for p in parts:
        if isinstance(node, dict):
            node = node.get(p)
        else:
            return key
    if node is None:
        return key
    text = str(node)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


def language_selector() -> None:
    """Render a language toggle in the sidebar."""
    labels = {"zh": "中文", "en": "English"}
    current = get_lang()
    choices = list(_SUPPORTED)
    idx = choices.index(current) if current in choices else 0
    selected = st.sidebar.selectbox(
        f"🌐 {t('app.language_label')}",
        choices,
        index=idx,
        format_func=lambda x: labels.get(x, x),
        key="lang_selector",
    )
    if selected != st.session_state.get("lang"):
        st.session_state["lang"] = selected
        st.rerun()
