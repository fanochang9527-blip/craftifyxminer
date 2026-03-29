"""Page 2: BD 审核工作台 — 汇总徽章 + 表格行 + 关键信号 + 操作按钮。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from auth.session import require_login

if not require_login():
    st.stop()

from dashboard.i18n import t
from db.connection import fetch_all, get_cursor
from dashboard.components.radar_chart import create_radar_chart

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

_CENTRALITY_OPTS = ["Hub", "Connector", "Peripheral"]
_CREATOR_TYPE_OPTS = ["oc_creator", "vtuber", "fan_artist", "game_creator", "content_creator"]
_STRATEGY_OPTS = ["seed_following", "geo_explore", "hashtag_explore", "time_explore"]
_BD_STATUS_OPTS = ["all", "ai_passed", "rule_passed", "pending", "interested", "rejected", "deferred"]


def _opt(prefix: str):
    return lambda v: t(f"options.{prefix}.{v}")


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

# ---------------------------------------------------------------------------
# Build query
# ---------------------------------------------------------------------------

where_clauses: list[str] = ["c.is_seed = false", "cs.sps_score IS NOT NULL", "cs.sps_score BETWEEN %s AND %s"]
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
           c.discovery_strategy, c.has_merch_experience, c.website,
           c.anchor_seed, c.discovered_via,
           cs.sps_score, cs.centrality_tier, cs.creator_type, cs.seed_connections,
           cf.audience_score, cf.engagement_score, cf.virality_score,
           cf.posting_score, cf.monetization_score, cf.growth_score,
           cf.circle_influence_score, cf.character_consistency,
           cf.community_score, cf.data_confidence
    FROM creators c
    JOIN creator_scores cs ON cs.creator_id = c.id
    LEFT JOIN creator_features cf ON cf.creator_id = c.id
    WHERE {where_sql}
    ORDER BY cs.sps_score DESC
    LIMIT 50
"""

candidates = fetch_all(query, tuple(params))

# ---------------------------------------------------------------------------
# Title + summary badges
# ---------------------------------------------------------------------------

st.title(t("candidates.title"))

hub_count = sum(1 for c in candidates if c.get("centrality_tier") == "Hub")
conn_count = sum(1 for c in candidates if c.get("centrality_tier") == "Connector")
high_sps_count = sum(1 for c in candidates if (c.get("sps_score") or 0) >= 75)

badge_cols = st.columns([2, 2, 2, 6])
with badge_cols[0]:
    st.metric(label=t("options.centrality.Hub"), value=hub_count)
with badge_cols[1]:
    st.metric(label=t("options.centrality.Connector"), value=conn_count)
with badge_cols[2]:
    st.metric(label=t("candidates.badge_high_sps"), value=high_sps_count)
with badge_cols[3]:
    st.markdown(f"**{t('candidates.match_count', count=len(candidates))}**")

st.markdown("---")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIER_STYLE = {
    "Hub": ("🟣", "#9b59b6"),
    "Connector": ("🟢", "#2ecc71"),
    "Peripheral": ("⚪", "#95a5a6"),
}

_FEATURE_KEYS = [
    "audience_score", "engagement_score", "virality_score",
    "posting_score", "monetization_score", "growth_score",
    "circle_influence_score", "character_consistency",
    "community_score", "data_confidence",
]

_RADAR_LABELS = [
    t("radar.audience"), t("radar.engagement"), t("radar.virality"),
    t("radar.posting"), t("radar.monetization"), t("radar.growth"),
    t("radar.circle_influence"), t("radar.character_consistency"),
    t("radar.community"), t("radar.data_confidence"),
]


def _build_signals(c: dict) -> str:
    """Derive key signal tags from feature scores and profile flags."""
    tags: list[str] = []

    if c.get("has_merch_experience"):
        tags.append(f"✅ {t('candidates.sig_has_merch')}")
    if c.get("website"):
        tags.append(f"✅ {t('candidates.sig_shop_link')}")

    score_checks = [
        ("audience_score", 80, "radar.audience"),
        ("engagement_score", 70, "radar.engagement"),
        ("virality_score", 70, "radar.virality"),
        ("growth_score", 70, "radar.growth"),
        ("community_score", 80, "radar.community"),
        ("character_consistency", 70, "radar.character_consistency"),
        ("circle_influence_score", 70, "radar.circle_influence"),
    ]
    for key, threshold, i18n_key in score_checks:
        val = c.get(key) or 0
        if val >= threshold:
            tags.append(f"✅ {t(i18n_key)}>{threshold}")

    monetization = c.get("monetization_score") or 0
    if monetization < 20:
        tags.append(f"⚠️ {t('candidates.sig_no_monetization')}")

    confidence = c.get("data_confidence") or 0
    if 0 < confidence < 60:
        tags.append(f"⚠️ {t('candidates.sig_low_confidence')}")

    return " ".join(tags) if tags else "—"


def _build_source(c: dict) -> str:
    """Format discovery source."""
    strategy = c.get("discovery_strategy") or ""
    anchor = c.get("anchor_seed") or ""
    via = c.get("discovered_via") or ""

    if strategy and anchor:
        label = t(f"options.strategy.{strategy}") if strategy in ("seed_following", "geo_explore", "hashtag_explore", "time_explore") else strategy
        return f"{label}: @{anchor}"
    if via:
        return via
    if strategy:
        return t(f"options.strategy.{strategy}") if strategy in ("seed_following", "geo_explore", "hashtag_explore", "time_explore") else strategy
    return "—"


# ---------------------------------------------------------------------------
# Table header
# ---------------------------------------------------------------------------

header_cols = st.columns([2, 1.2, 0.8, 4, 2, 2.5])
header_cols[0].markdown(f"**{t('candidates.col_creator')}**")
header_cols[1].markdown(f"**{t('candidates.centrality')}**")
header_cols[2].markdown(f"**SPS**")
header_cols[3].markdown(f"**{t('candidates.col_signals')}**")
header_cols[4].markdown(f"**{t('candidates.col_source')}**")
header_cols[5].markdown(f"**{t('candidates.col_actions')}**")
st.markdown("---")

# ---------------------------------------------------------------------------
# Candidate rows
# ---------------------------------------------------------------------------

for c in candidates:
    cid = c["id"]
    tier = c.get("centrality_tier") or "Peripheral"
    emoji, _ = _TIER_STYLE.get(tier, ("⚪", "#95a5a6"))
    sps = float(c.get("sps_score") or 0)
    signals = _build_signals(c)
    source = _build_source(c)

    row_cols = st.columns([2, 1.2, 0.8, 4, 2, 2.5])

    with row_cols[0]:
        st.markdown(f"[@{c['username']}](https://x.com/{c['username']})")

    with row_cols[1]:
        st.markdown(f"{emoji} {t(f'options.centrality.{tier}')}")

    with row_cols[2]:
        st.markdown(f"**{sps:.1f}**")

    with row_cols[3]:
        st.markdown(signals)

    with row_cols[4]:
        st.caption(source)

    with row_cols[5]:
        bcols = st.columns(4)
        with bcols[0]:
            if st.button("✅", key=f"int_{cid}", help=t("candidates.btn_interested")):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'interested', bd_status = 'interested', last_bd_update = NOW() WHERE id = %s",
                        (cid,),
                    )
                st.toast(t("candidates.marked_interested"))
                st.rerun()
        with bcols[1]:
            if st.button("❌", key=f"rej_{cid}", help=t("candidates.btn_rejected")):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'rejected', bd_status = 'rejected', last_bd_update = NOW() WHERE id = %s",
                        (cid,),
                    )
                st.toast(t("candidates.marked_rejected"))
                st.rerun()
        with bcols[2]:
            if st.button("⚠️", key=f"flag_{cid}", help=t("candidates.btn_flag")):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'flagged', bd_status = 'pending', last_bd_update = NOW() WHERE id = %s",
                        (cid,),
                    )
                st.toast(t("candidates.marked_flagged"))
                st.rerun()
        with bcols[3]:
            if st.button("⏸️", key=f"def_{cid}", help=t("candidates.btn_deferred")):
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_decision = 'deferred', bd_status = 'deferred', last_bd_update = NOW() WHERE id = %s",
                        (cid,),
                    )
                st.toast(t("candidates.marked_deferred"))
                st.rerun()

    with st.expander(f"📊 {t('candidates.detail_radar')} — @{c['username']}", expanded=False):
        detail_left, detail_right = st.columns([3, 2])
        with detail_left:
            if c.get("bio"):
                st.text(c["bio"][:300])
            ctype = c.get("creator_type") or ""
            ctype_display = t(f"options.creator_type.{ctype}") if ctype else "N/A"
            followers_val = c.get("followers", 0) or 0
            seeds_val = c.get("seed_connections", 0) or 0
            st.caption(
                f"{t('candidates.type_label')}: {ctype_display} | "
                f"{t('candidates.followers_label')}: {followers_val:,} | "
                f"{t('candidates.seed_connections_label')}: {seeds_val}"
            )
            note = st.text_input(
                t("candidates.note_placeholder"),
                key=f"note_{cid}",
                label_visibility="collapsed",
                placeholder=t("candidates.note_placeholder"),
            )
            if note:
                with get_cursor() as cur:
                    cur.execute("UPDATE creators SET bd_decision_note = %s WHERE id = %s", (note, cid))

        with detail_right:
            features = {k: c.get(k, 0) for k in _FEATURE_KEYS}
            fig = create_radar_chart(features, f"@{c['username']}", labels=_RADAR_LABELS)
            st.plotly_chart(fig, use_container_width=True, key=f"radar_{cid}")

    st.markdown("<hr style='margin:2px 0;border-color:#333'>", unsafe_allow_html=True)
