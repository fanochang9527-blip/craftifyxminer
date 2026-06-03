"""Streamlit BD Dashboard 主入口 — st.navigation() 集中路由。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

st.set_page_config(
    page_title="CraftifyX Miner",
    page_icon="⛏️",
    layout="wide",
    initial_sidebar_state="expanded",
)

from auth.session import require_login, logout  # noqa: E402
from dashboard.i18n import t, language_selector  # noqa: E402

user = require_login()
if not user:
    st.stop()

pages = [
    st.Page("page_modules/0_home.py", title=t("nav.home"), icon="🏠"),
    st.Page("page_modules/1_daily_report.py", title=t("nav.daily_report"), icon="📊"),
    st.Page("page_modules/2_candidates.py", title=t("nav.candidates"), icon="👤"),
    st.Page("page_modules/3_outreach.py", title=t("nav.outreach"), icon="📞"),
    st.Page("page_modules/4_cost_monitor.py", title=t("nav.cost_monitor"), icon="💸"),
    st.Page("page_modules/6_seeds.py", title=t("nav.seeds"), icon="🌱"),
]

if user.get("role") == "admin":
    pages.append(st.Page("page_modules/5_admin.py", title=t("nav.admin"), icon="⚙️"))

pg = st.navigation(pages)

st.sidebar.title(t("app.sidebar_title"))
st.sidebar.caption(f"👤 {user.get('display_name', user['username'])}  ({user['role']})")
if st.sidebar.button(t("app.logout")):
    logout()
    st.rerun()
language_selector()
st.sidebar.markdown("---")

pg.run()
