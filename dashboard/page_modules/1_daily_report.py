"""Page 1: 每日发现报告 — 今日候选数、中心度分布、SPS 筛选、趋势图。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from auth.session import require_login

if not require_login():
    st.stop()

import pandas as pd
import plotly.express as px

from dashboard.i18n import t
from db.connection import fetch_all, fetch_one

st.title(t("daily.title"))

today_stats = fetch_one(
    """SELECT
           COUNT(*) FILTER (WHERE discovered_date = CURRENT_DATE) AS today_total,
           COUNT(*) FILTER (WHERE bd_status IN ('rule_passed', 'ai_passed') AND discovered_date = CURRENT_DATE) AS today_passed,
           COUNT(*) FILTER (WHERE bd_status IN ('rule_rejected', 'ai_rejected', 'content_rejected') AND discovered_date = CURRENT_DATE) AS today_rejected
       FROM creators"""
) or {}

col1, col2, col3 = st.columns(3)
col1.metric(t("daily.today_discovered"), today_stats.get("today_total", 0))
col2.metric(t("daily.today_passed"), today_stats.get("today_passed", 0))
col3.metric(t("daily.today_rejected"), today_stats.get("today_rejected", 0))

st.markdown("---")

st.subheader(t("daily.centrality_dist"))
centrality_data = fetch_all(
    """SELECT centrality_tier, COUNT(*) AS cnt
       FROM creator_scores cs
       JOIN creators c ON c.id = cs.creator_id
       WHERE c.discovered_date = CURRENT_DATE
       GROUP BY centrality_tier"""
)
if centrality_data:
    df_c = pd.DataFrame(centrality_data)
    df_c["_label"] = df_c["centrality_tier"].apply(
        lambda x: t(f"options.centrality.{x}") if x else ""
    )
    fig_c = px.pie(df_c, values="cnt", names="_label",
                   color_discrete_sequence=["#636EFA", "#EF553B", "#00CC96"])
    st.plotly_chart(fig_c, use_container_width=True)
else:
    st.info(t("daily.no_centrality"))

st.subheader(t("daily.high_sps"))
high_sps = fetch_all(
    """SELECT c.username, cs.sps_score, cs.centrality_tier, cs.seed_connections
       FROM creator_scores cs
       JOIN creators c ON c.id = cs.creator_id
       WHERE cs.sps_score > 75 AND c.discovered_date = CURRENT_DATE
       ORDER BY cs.sps_score DESC
       LIMIT 20"""
)
if high_sps:
    df_h = pd.DataFrame(high_sps)
    df_h["centrality_tier"] = df_h["centrality_tier"].apply(
        lambda x: t(f"options.centrality.{x}") if x else ""
    )
    df_h = df_h.rename(columns={
        "username": t("outreach.col_username"),
        "sps_score": t("outreach.col_sps"),
        "centrality_tier": t("candidates.centrality"),
        "seed_connections": t("candidates.seed_connections_label"),
    })
    st.dataframe(df_h, use_container_width=True)
else:
    st.info(t("daily.no_high_sps"))

st.subheader(t("daily.weekly_trend"))
trend_data = fetch_all(
    """SELECT discovered_date::text AS date, COUNT(*) AS total,
              COUNT(*) FILTER (WHERE bd_status IN ('rule_passed', 'ai_passed')) AS passed,
              COUNT(*) FILTER (WHERE bd_status IN ('rule_rejected', 'ai_rejected', 'content_rejected')) AS rejected
       FROM creators
       WHERE discovered_date >= CURRENT_DATE - INTERVAL '7 days'
       GROUP BY discovered_date
       ORDER BY discovered_date"""
)
if trend_data:
    df_trend = pd.DataFrame(trend_data)
    st_col = t("chart.series_total")
    pass_col = t("chart.series_passed")
    rej_col = t("chart.series_rejected")
    df_trend = df_trend.rename(columns={"total": st_col, "passed": pass_col, "rejected": rej_col})
    fig_t = px.line(
        df_trend,
        x="date",
        y=[st_col, pass_col, rej_col],
        labels={
            "value": t("chart.count"),
            "variable": t("chart.type"),
            "date": t("chart.date_axis"),
        },
        title=t("daily.trend_title"),
    )
    st.plotly_chart(fig_t, use_container_width=True)

st.subheader(t("daily.strategy_dist"))
strategy_data = fetch_all(
    """SELECT discovery_strategy, COUNT(*) AS cnt
       FROM creators
       WHERE discovered_date = CURRENT_DATE AND discovery_strategy IS NOT NULL
       GROUP BY discovery_strategy"""
)
if strategy_data:
    df_s = pd.DataFrame(strategy_data)
    df_s["_label"] = df_s["discovery_strategy"].apply(
        lambda x: t(f"options.strategy.{x}") if x else ""
    )
    fig_s = px.pie(df_s, values="cnt", names="_label",
                   color_discrete_sequence=["#00CC96", "#636EFA", "#FECB52", "#AB63FA"])
    st.plotly_chart(fig_s, use_container_width=True)
