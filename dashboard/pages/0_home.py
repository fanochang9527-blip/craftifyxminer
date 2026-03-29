"""首页 — 欢迎与导航说明。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from auth.session import require_login

if not require_login():
    st.stop()

from dashboard.i18n import t

st.title(t("app.title"))
st.markdown(t("app.welcome"))
