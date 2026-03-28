"""Page 4: 成本监控面板 — 日/月成本, 预算进度条, 超预算预警。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px

from config.settings import DAILY_APIFY_BUDGET_USD, MONTHLY_BUDGET_USD, MONTHLY_LLM_BUDGET_USD
from db.connection import fetch_all, fetch_one

st.set_page_config(page_title="Cost Monitor", layout="wide")
st.title("💸 成本监控面板")

# --- 今日成本 ---
today = fetch_one("SELECT * FROM cost_tracking WHERE date = CURRENT_DATE") or {}
mtd = fetch_one(
    """SELECT
           COALESCE(SUM(apify_cost_usd), 0) AS mtd_apify,
           COALESCE(SUM(llm_cost_usd), 0) AS mtd_llm,
           COALESCE(SUM(proxy_cost_usd), 0) AS mtd_proxy,
           COALESCE(SUM(total_cost_usd), 0) AS mtd_total
       FROM cost_tracking
       WHERE date >= date_trunc('month', CURRENT_DATE)"""
) or {}

st.subheader("今日成本")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Apify CU", f"${float(today.get('apify_cost_usd', 0)):.2f}")
col2.metric("LLM Tokens", f"{int(today.get('llm_tokens_used', 0)):,}")
col3.metric("LLM 费用", f"${float(today.get('llm_cost_usd', 0)):.4f}")
col4.metric("今日总计", f"${float(today.get('total_cost_usd', 0)):.2f}")

st.markdown("---")

# --- 月度预算消耗 ---
st.subheader("月度预算消耗")
mtd_total = float(mtd.get("mtd_total", 0))
mtd_llm = float(mtd.get("mtd_llm", 0))

col_budget1, col_budget2 = st.columns(2)

with col_budget1:
    progress = min(mtd_total / MONTHLY_BUDGET_USD, 1.0) if MONTHLY_BUDGET_USD > 0 else 0
    st.metric("本月累计", f"${mtd_total:.2f} / ${MONTHLY_BUDGET_USD:.0f}")
    st.progress(progress)
    if mtd_total > MONTHLY_BUDGET_USD * 0.8:
        st.error(f"⚠️ 月度总预算已消耗 {progress * 100:.0f}%，请注意控制!")

with col_budget2:
    llm_progress = min(mtd_llm / MONTHLY_LLM_BUDGET_USD, 1.0) if MONTHLY_LLM_BUDGET_USD > 0 else 0
    st.metric("LLM 月累计", f"${mtd_llm:.2f} / ${MONTHLY_LLM_BUDGET_USD:.0f}")
    st.progress(llm_progress)

# --- 超预算预警 ---
today_total = float(today.get("total_cost_usd", 0))
if today_total > 25:
    st.error(f"🚨 今日成本 ${today_total:.2f} 超过 $25 日预警线!")
if mtd_total > 400:
    st.warning(f"⚠️ 月累计 ${mtd_total:.2f} 超过 $400 预警线!")

st.markdown("---")

# --- 分项明细 ---
st.subheader("月度成本构成")
if mtd:
    breakdown = {
        "Apify": float(mtd.get("mtd_apify", 0)),
        "LLM": float(mtd.get("mtd_llm", 0)),
        "Proxy": float(mtd.get("mtd_proxy", 0)),
    }
    df_bd = pd.DataFrame(list(breakdown.items()), columns=["Category", "Cost USD"])
    fig_bd = px.pie(df_bd, values="Cost USD", names="Category", title="本月成本构成")
    st.plotly_chart(fig_bd, use_container_width=True)

# --- 日均成本趋势 ---
st.subheader("日成本趋势 (近 30 天)")
daily_costs = fetch_all(
    """SELECT date::text, total_cost_usd, apify_cost_usd, llm_cost_usd, proxy_cost_usd
       FROM cost_tracking
       WHERE date >= CURRENT_DATE - INTERVAL '30 days'
       ORDER BY date"""
)
if daily_costs:
    df_dc = pd.DataFrame(daily_costs)
    fig_dc = px.line(
        df_dc, x="date",
        y=["total_cost_usd", "apify_cost_usd", "llm_cost_usd", "proxy_cost_usd"],
        labels={"value": "Cost (USD)", "variable": "Category"},
        title="日成本趋势",
    )
    st.plotly_chart(fig_dc, use_container_width=True)
else:
    st.info("暂无历史成本数据")
