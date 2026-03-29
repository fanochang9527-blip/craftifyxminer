"""Page 2: 候选人浏览与 BD 判定 — 筛选器 + 候选人卡片 + 雷达图 + BD 操作。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd

from auth.session import require_login

if not require_login():
    st.stop()

from dashboard.i18n import t
from db.connection import fetch_all, get_cursor
from dashboard.components.radar_chart import create_radar_chart

st.title(t("candidates.title"))


def _opt(prefix: str):
    """Return a format_func that translates DB enum values via options.{prefix}.{value}."""
    return lambda v: t(f"options.{prefix}.{v}")


_CENTRALITY_OPTS = ["Hub", "Connector", "Peripheral"]
_CREATOR_TYPE_OPTS = ["oc_creator", "vtuber", "fan_artist", "game_creator", "content_creator"]
_STRATEGY_OPTS = ["seed_following", "geo_explore", "hashtag_explore", "time_explore"]
_BD_STATUS_OPTS = ["ai_passed", "rule_passed", "pending", "interested", "rejected", "deferred", "all"]

with st.sidebar:
    st.header(t("candidates.filter_header"))
    centrality_filter = st.multiselect(
        t("candidates.centrality"),
        _CENTRALITY_OPTS,
        default=_CENTRALITY_OPTS,
        format_func=_opt("centrality"),
    )
    sps_min, sps_max = st.slider(t("candidates.sps_range"), 0, 100, (0, 100))
    creator_types = st.multiselect(
        t("candidates.creator_type"),
        _CREATOR_TYPE_OPTS,
        default=_CREATOR_TYPE_OPTS,
        format_func=_opt("creator_type"),
    )
    strategy_filter = st.multiselect(
        t("candidates.strategy"),
        _STRATEGY_OPTS,
        format_func=_opt("strategy"),
    )
    bd_status_filter = st.selectbox(
        t("candidates.bd_status"),
        _BD_STATUS_OPTS,
        index=0,
        format_func=_opt("bd_status"),
    )

where_clauses = ["cs.sps_score BETWEEN %s AND %s"]
params: list = [sps_min, sps_max]

if centrality_filter:
    where_clauses.append("cs.centrality_tier = ANY(%s)")
    params.append(centrality_filter)

if creator_types:
    where_clauses.append("cs.creator_type = ANY(%s)")
    params.append(creator_types)

if strategy_filter:
    where_clauses.append("c.discovery_strategy = ANY(%s)")
    params.append(strategy_filter)

if bd_status_filter != "all":
    where_clauses.append("c.bd_status = %s")
    params.append(bd_status_filter)

where_sql = " AND ".join(where_clauses)
query = f"""
    SELECT c.id, c.username, c.bio, c.followers, c.bd_status, c.bd_decision,
           c.discovery_strategy, c.has_merch_experience,
           cs.sps_score, cs.centrality_tier, cs.creator_type, cs.seed_connections,
           cf.*
    FROM creators c
    JOIN creator_scores cs ON cs.creator_id = c.id
    LEFT JOIN creator_features cf ON cf.creator_id = c.id
    WHERE {where_sql}
    ORDER BY cs.sps_score DESC
    LIMIT 50
"""

candidates = fetch_all(query, tuple(params))

st.markdown(f"**{t('candidates.match_count', count=len(candidates))}**")

_radar_labels = [
    t("radar.audience"), t("radar.engagement"), t("radar.virality"),
    t("radar.posting"), t("radar.monetization"), t("radar.growth"),
    t("radar.circle_influence"), t("radar.character_consistency"),
    t("radar.community"), t("radar.data_confidence"),
]

for c in candidates:
    with st.container():
        col_info, col_chart = st.columns([3, 2])

        with col_info:
            tier_badge = {"Hub": "🔴", "Connector": "🟡", "Peripheral": "🟢"}.get(c.get("centrality_tier"), "⚪")
            st.markdown(
                f"### {tier_badge} [@{c['username']}](https://x.com/{c['username']}) "
                f"— SPS **{c.get('sps_score', 0):.1f}**"
            )
            creator_type_display = t(f"options.creator_type.{c.get('creator_type', '')}") if c.get("creator_type") else "N/A"
            strategy_display = t(f"options.strategy.{c.get('discovery_strategy', '')}") if c.get("discovery_strategy") else "N/A"
            st.caption(
                f"{t('candidates.type_label')}: {creator_type_display} | "
                f"{t('candidates.seed_connections_label')}: {c.get('seed_connections', 0)} | "
                f"{t('candidates.followers_label')}: {c.get('followers', 0):,} | "
                f"{t('candidates.strategy_label')}: {strategy_display}"
            )
            if c.get("bio"):
                st.text(c["bio"][:200])
            if c.get("has_merch_experience"):
                st.success(t("candidates.merch_exp"))

        with col_chart:
            features = {k: c.get(k, 0) for k in [
                "audience_score", "engagement_score", "virality_score",
                "posting_score", "monetization_score", "growth_score",
                "circle_influence_score", "character_consistency",
                "community_score", "data_confidence",
            ]}
            fig = create_radar_chart(features, f"@{c['username']}", labels=_radar_labels)
            st.plotly_chart(fig, use_container_width=True, key=f"radar_{c['id']}")

        col_btn1, col_btn2, col_btn3, col_note = st.columns([1, 1, 1, 3])
        creator_id = c["id"]

        with col_btn1:
            if st.button(t("candidates.btn_interested"), key=f"int_{creator_id}"):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'interested', bd_status = 'interested', last_bd_update = NOW() WHERE id = %s",
                        (creator_id,),
                    )
                st.success(t("candidates.marked_interested"))

        with col_btn2:
            if st.button(t("candidates.btn_rejected"), key=f"rej_{creator_id}"):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'rejected', bd_status = 'rejected', last_bd_update = NOW() WHERE id = %s",
                        (creator_id,),
                    )
                st.warning(t("candidates.marked_rejected"))

        with col_btn3:
            if st.button(t("candidates.btn_deferred"), key=f"def_{creator_id}"):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'deferred', bd_status = 'deferred', last_bd_update = NOW() WHERE id = %s",
                        (creator_id,),
                    )
                st.info(t("candidates.marked_deferred"))

        with col_note:
            note = st.text_input(t("candidates.note_placeholder"), key=f"note_{creator_id}", label_visibility="collapsed", placeholder=t("candidates.note_placeholder"))
            if note:
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision_note = %s WHERE id = %s",
                        (note, creator_id),
                    )

        st.markdown("---")
