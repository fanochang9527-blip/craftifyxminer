"""Streamlit BD Dashboard 主入口。"""

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

st.sidebar.title("CraftifyX Miner 7.0")
st.sidebar.markdown("---")

st.title("CraftifyX Miner Dashboard")
st.markdown(
    """
    欢迎使用 CraftifyX Miner 7.0 BD Dashboard。

    **导航页面** (侧边栏):
    - **Daily Report** — 每日发现报告
    - **Candidates** — 候选人浏览与 BD 判定
    - **Outreach** — 联系追踪与销售反馈
    - **Cost Monitor** — 成本监控面板
    """
)
