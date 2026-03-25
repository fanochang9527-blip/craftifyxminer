"""Page 1: 每日发现报告 — 今日候选数、中心度分布、SPS 筛选、趋势图。"""

import streamlit as st
import pandas as pd
import plotly.express as px

from db.connection import fetch_all, fetch_one

st.set_page_config(page_title="Daily Report", layout="wide")
st.title("📊 每日发现报告")

# --- 今日概览 ---
today_stats = fetch_one(
    """SELECT
           COUNT(*) FILTER (WHERE discovered_date = CURRENT_DATE) AS today_total,
           COUNT(*) FILTER (WHERE bd_status IN ('rule_passed', 'ai_passed') AND discovered_date = CURRENT_DATE) AS today_passed,
           COUNT(*) FILTER (WHERE bd_status IN ('rule_rejected', 'ai_rejected') AND discovered_date = CURRENT_DATE) AS today_rejected
       FROM creators"""
) or {}

col1, col2, col3 = st.columns(3)
col1.metric("今日新发现", today_stats.get("today_total", 0))
col2.metric("过滤通过", today_stats.get("today_passed", 0))
col3.metric("过滤淘汰", today_stats.get("today_rejected", 0))

st.markdown("---")

# --- 中心度分布 ---
st.subheader("Hub / Connector / Peripheral 分布")
centrality_data = fetch_all(
    """SELECT centrality_tier, COUNT(*) AS cnt
       FROM creator_scores cs
       JOIN creators c ON c.id = cs.creator_id
       WHERE c.discovered_date = CURRENT_DATE
       GROUP BY centrality_tier"""
)
if centrality_data:
    df_c = pd.DataFrame(centrality_data)
    fig_c = px.pie(df_c, values="cnt", names="centrality_tier",
                   color_discrete_sequence=["#636EFA", "#EF553B", "#00CC96"])
    st.plotly_chart(fig_c, use_container_width=True)
else:
    st.info("今日暂无中心度数据")

# --- SPS > 75 ---
st.subheader("高潜候选 (SPS > 75)")
high_sps = fetch_all(
    """SELECT c.username, cs.sps_score, cs.centrality_tier, cs.seed_connections
       FROM creator_scores cs
       JOIN creators c ON c.id = cs.creator_id
       WHERE cs.sps_score > 75 AND c.discovered_date = CURRENT_DATE
       ORDER BY cs.sps_score DESC
       LIMIT 20"""
)
if high_sps:
    st.dataframe(pd.DataFrame(high_sps), use_container_width=True)
else:
    st.info("今日暂无 SPS > 75 的候选人")

# --- 本周趋势 ---
st.subheader("本周发现趋势")
trend_data = fetch_all(
    """SELECT discovered_date::text AS date, COUNT(*) AS total,
              COUNT(*) FILTER (WHERE bd_status IN ('rule_passed', 'ai_passed')) AS passed
       FROM creators
       WHERE discovered_date >= CURRENT_DATE - INTERVAL '7 days'
       GROUP BY discovered_date
       ORDER BY discovered_date"""
)
if trend_data:
    df_t = pd.DataFrame(trend_data)
    fig_t = px.line(df_t, x="date", y=["total", "passed"],
                    labels={"value": "Count", "variable": "Type"},
                    title="7 日发现趋势")
    st.plotly_chart(fig_t, use_container_width=True)

# --- 常规 vs 探索占比 ---
st.subheader("发现策略分布")
strategy_data = fetch_all(
    """SELECT discovery_strategy, COUNT(*) AS cnt
       FROM creators
       WHERE discovered_date = CURRENT_DATE AND discovery_strategy IS NOT NULL
       GROUP BY discovery_strategy"""
)
if strategy_data:
    df_s = pd.DataFrame(strategy_data)
    fig_s = px.pie(df_s, values="cnt", names="discovery_strategy",
                   color_discrete_sequence=["#00CC96", "#636EFA", "#FECB52", "#AB63FA"])
    st.plotly_chart(fig_s, use_container_width=True)
