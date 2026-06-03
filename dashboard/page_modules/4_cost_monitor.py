"""Page 4: 成本监控面板 — 日/月成本, 预算进度条, 超预算预警。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from auth.session import require_login

if not require_login():
    st.stop()

import pandas as pd
import plotly.express as px

from config.settings import MONTHLY_BUDGET_USD, MONTHLY_LLM_BUDGET_USD
from dashboard.i18n import t
from db.connection import fetch_all, fetch_one

st.title(t("cost.title"))

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

st.subheader(t("cost.today_cost"))
col1, col2, col3, col4 = st.columns(4)
col1.metric(t("cost.apify_cu"), f"${float(today.get('apify_cost_usd', 0)):.2f}")
col2.metric(t("cost.llm_tokens"), f"{int(today.get('llm_tokens_used', 0)):,}")
col3.metric(t("cost.llm_cost"), f"${float(today.get('llm_cost_usd', 0)):.4f}")
col4.metric(t("cost.today_total"), f"${float(today.get('total_cost_usd', 0)):.2f}")

st.markdown("---")

st.subheader(t("cost.monthly_budget"))
mtd_total = float(mtd.get("mtd_total", 0))
mtd_llm = float(mtd.get("mtd_llm", 0))

col_budget1, col_budget2 = st.columns(2)

with col_budget1:
    progress = min(mtd_total / MONTHLY_BUDGET_USD, 1.0) if MONTHLY_BUDGET_USD > 0 else 0
    st.metric(t("cost.mtd_total"), f"${mtd_total:.2f} / ${MONTHLY_BUDGET_USD:.0f}")
    st.progress(progress)
    if mtd_total > MONTHLY_BUDGET_USD * 0.8:
        st.error(t("cost.budget_warning", pct=f"{progress * 100:.0f}"))

with col_budget2:
    llm_progress = min(mtd_llm / MONTHLY_LLM_BUDGET_USD, 1.0) if MONTHLY_LLM_BUDGET_USD > 0 else 0
    st.metric(t("cost.mtd_llm"), f"${mtd_llm:.2f} / ${MONTHLY_LLM_BUDGET_USD:.0f}")
    st.progress(llm_progress)

today_total = float(today.get("total_cost_usd", 0))
if today_total > 25:
    st.error(t("cost.daily_alert", cost=f"{today_total:.2f}"))
if mtd_total > 400:
    st.warning(t("cost.monthly_alert", cost=f"{mtd_total:.2f}"))

st.markdown("---")

st.subheader(t("cost.breakdown"))
if mtd:
    cat_col = t("chart.category")
    cost_col = t("chart.cost_usd")
    df_bd = pd.DataFrame(
        [
            (t("chart.cat_apify"), float(mtd.get("mtd_apify", 0))),
            (t("chart.cat_llm"), float(mtd.get("mtd_llm", 0))),
            (t("chart.cat_proxy"), float(mtd.get("mtd_proxy", 0))),
        ],
        columns=[cat_col, cost_col],
    )
    fig_bd = px.pie(df_bd, values=cost_col, names=cat_col, title=t("cost.breakdown_title"))
    st.plotly_chart(fig_bd, use_container_width=True)

st.subheader(t("cost.daily_trend"))
daily_costs = fetch_all(
    """SELECT date::text, total_cost_usd, apify_cost_usd, llm_cost_usd, proxy_cost_usd
       FROM cost_tracking
       WHERE date >= CURRENT_DATE - INTERVAL '30 days'
       ORDER BY date"""
)
if daily_costs:
    df_dc = pd.DataFrame(daily_costs)
    y_total = t("chart.total_cost_usd")
    y_apify = t("chart.apify_cost_usd")
    y_llm = t("chart.llm_cost_usd")
    y_proxy = t("chart.proxy_cost_usd")
    df_dc = df_dc.rename(columns={
        "total_cost_usd": y_total,
        "apify_cost_usd": y_apify,
        "llm_cost_usd": y_llm,
        "proxy_cost_usd": y_proxy,
    })
    fig_dc = px.line(
        df_dc,
        x="date",
        y=[y_total, y_apify, y_llm, y_proxy],
        labels={
            "value": t("chart.cost_usd"),
            "variable": t("chart.category"),
            "date": t("chart.date_axis"),
        },
        title=t("cost.daily_trend_title"),
    )
    st.plotly_chart(fig_dc, use_container_width=True)
else:
    st.info(t("cost.no_history"))
