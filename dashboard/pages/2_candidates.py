"""Page 2: 候选人浏览与 BD 判定 — 筛选器 + 候选人卡片 + 雷达图 + BD 操作。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd

from db.connection import fetch_all, get_cursor
from dashboard.components.radar_chart import create_radar_chart

st.set_page_config(page_title="Candidates", layout="wide")
st.title("👤 候选人浏览与 BD 判定")

# --- 筛选器 ---
with st.sidebar:
    st.header("筛选条件")
    centrality_filter = st.multiselect(
        "中心度",
        ["Hub", "Connector", "Peripheral"],
        default=["Hub", "Connector", "Peripheral"],
    )
    sps_min, sps_max = st.slider("SPS 范围", 0, 100, (0, 100))
    creator_types = st.multiselect(
        "创作者类型",
        ["oc_creator", "vtuber", "fan_artist", "game_creator", "content_creator"],
        default=["oc_creator", "vtuber", "fan_artist", "game_creator", "content_creator"],
    )
    strategy_filter = st.multiselect(
        "发现策略",
        ["seed_following", "geo_explore", "hashtag_explore", "time_explore"],
    )
    bd_status_filter = st.selectbox(
        "BD 状态",
        ["ai_passed", "rule_passed", "pending", "interested", "rejected", "deferred", "all"],
        index=0,
    )

# --- 构建查询 ---
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

st.markdown(f"**共 {len(candidates)} 个候选人匹配筛选条件**")

# --- 候选人卡片 ---
for c in candidates:
    with st.container():
        col_info, col_chart = st.columns([3, 2])

        with col_info:
            tier_badge = {"Hub": "🔴", "Connector": "🟡", "Peripheral": "🟢"}.get(c.get("centrality_tier"), "⚪")
            st.markdown(
                f"### {tier_badge} [@{c['username']}](https://x.com/{c['username']}) "
                f"— SPS **{c.get('sps_score', 0):.1f}**"
            )
            st.caption(f"类型: {c.get('creator_type', 'N/A')} | "
                       f"Seed Connections: {c.get('seed_connections', 0)} | "
                       f"Followers: {c.get('followers', 0):,} | "
                       f"策略: {c.get('discovery_strategy', 'N/A')}")
            if c.get("bio"):
                st.text(c["bio"][:200])
            if c.get("has_merch_experience"):
                st.success("✅ 有商品化经验")

        with col_chart:
            features = {k: c.get(k, 0) for k in [
                "audience_score", "engagement_score", "virality_score",
                "posting_score", "monetization_score", "growth_score",
                "circle_influence_score", "character_consistency",
                "community_score", "data_confidence",
            ]}
            fig = create_radar_chart(features, f"@{c['username']}")
            st.plotly_chart(fig, use_container_width=True, key=f"radar_{c['id']}")

        # BD 操作
        col_btn1, col_btn2, col_btn3, col_note = st.columns([1, 1, 1, 3])
        creator_id = c["id"]

        with col_btn1:
            if st.button("✅ Interested", key=f"int_{creator_id}"):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'interested', bd_status = 'interested', last_bd_update = NOW() WHERE id = %s",
                        (creator_id,),
                    )
                st.success("已标记 Interested")

        with col_btn2:
            if st.button("❌ Rejected", key=f"rej_{creator_id}"):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'rejected', bd_status = 'rejected', last_bd_update = NOW() WHERE id = %s",
                        (creator_id,),
                    )
                st.warning("已标记 Rejected")

        with col_btn3:
            if st.button("⏸️ Deferred", key=f"def_{creator_id}"):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'deferred', bd_status = 'deferred', last_bd_update = NOW() WHERE id = %s",
                        (creator_id,),
                    )
                st.info("已标记 Deferred")

        with col_note:
            note = st.text_input("备注", key=f"note_{creator_id}", label_visibility="collapsed", placeholder="添加备注...")
            if note:
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision_note = %s WHERE id = %s",
                        (note, creator_id),
                    )

        st.markdown("---")
