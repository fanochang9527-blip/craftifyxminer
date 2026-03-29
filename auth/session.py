"""Streamlit session helpers — login gate and role checks."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    pass

SESSION_TIMEOUT_SECONDS = 8 * 3600


def require_login() -> dict | None:
    """Check session state; return user dict if logged in, else show login form and return None."""
    user = st.session_state.get("user")
    login_time = st.session_state.get("login_time", 0)

    if user and (time.time() - login_time) < SESSION_TIMEOUT_SECONDS:
        return user

    if user:
        st.session_state.pop("user", None)
        st.session_state.pop("login_time", None)
        st.warning("会话已过期，请重新登录")

    _show_login_form()
    return None


def _show_login_form() -> None:
    from auth.login import attempt_login
    from dashboard.i18n import t

    st.markdown(f"### {t('login.title')}")
    with st.form("login_form"):
        username = st.text_input(t("login.username"))
        password = st.text_input(t("login.password"), type="password")
        submitted = st.form_submit_button(t("login.submit"), use_container_width=True)

    if submitted and username and password:
        result = attempt_login(username, password)
        if result["ok"]:
            st.session_state["user"] = result["user"]
            st.session_state["login_time"] = time.time()
            st.rerun()
        else:
            st.error(result["error"])


def require_role(role: str) -> bool:
    """Return True if current user has the required role."""
    user = st.session_state.get("user")
    if not user:
        return False
    if role == "admin":
        return user.get("role") == "admin"
    return True


def logout() -> None:
    st.session_state.pop("user", None)
    st.session_state.pop("login_time", None)
