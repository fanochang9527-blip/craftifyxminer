"""Page 2: BD 审核工作台 — 汇总徽章 + 表格行 + 关键信号 + 操作按钮。"""

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from auth.session import require_login, get_bd_distribution_info

if not require_login():
    st.stop()

from dashboard.i18n import t
from config.settings import BD_WORKBENCH_PHASE, NON_SELLABLE_SPS_WEIGHT
from db.connection import fetch_all, fetch_one, get_cursor
from dashboard.components.radar_chart import create_radar_chart
from dashboard.candidates_query import (
    BD_STATUS_OPTS,
    CENTRALITY_OPTS,
    CREATOR_TYPE_OPTS,
    STRATEGY_OPTS,
    build_assigned_count_sql,
    build_assigned_data_sql,
    build_where_clauses,
    calc_pagination,
)


def _render_pagination_controls(
    *, page: int, total_pages: int, total_count: int, key_prefix: str
) -> None:
    pag_cols = st.columns([2, 2, 1.5, 1.5, 2, 1])
    with pag_cols[0]:
        st.caption(t("candidates.page_info", page=page, total_pages=total_pages, total=total_count))
    with pag_cols[1]:
        if st.button("⬅️", disabled=(page <= 1), key=f"prev_{key_prefix}"):
            st.session_state["candidates_page"] = page - 1
            st.session_state["candidates_detail_open_id"] = None
            st.rerun()
    with pag_cols[2]:
        jump_page = st.number_input(
            t("candidates.jump"),
            min_value=1,
            max_value=total_pages,
            value=page,
            key=f"jump_input_{key_prefix}",
            label_visibility="collapsed",
        )
    with pag_cols[3]:
        if st.button(t("candidates.jump"), key=f"jump_btn_{key_prefix}"):
            if jump_page != page:
                st.session_state["candidates_page"] = int(jump_page)
                st.session_state["candidates_detail_open_id"] = None
                st.rerun()
    with pag_cols[4]:
        if st.button("➡️", disabled=(page >= total_pages), key=f"next_{key_prefix}"):
            st.session_state["candidates_page"] = page + 1
            st.session_state["candidates_detail_open_id"] = None
            st.rerun()


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

def _opt(prefix: str):
    return lambda v: t(f"options.{prefix}.{v}")


with st.sidebar:
    st.header(t("candidates.filter_header"))
    centrality_filter = st.multiselect(
        t("candidates.centrality"),
        CENTRALITY_OPTS,
        default=CENTRALITY_OPTS,
        format_func=_opt("centrality"),
    )
    sps_min, sps_max = st.slider(t("candidates.sps_range"), 0, 100, (0, 100))
    sellability_min, sellability_max = st.slider(t("candidates.sellability_range"), 0, 100, (0, 100))
    pred_sales_min, pred_sales_max = st.slider(
        t("candidates.pred_sales_range"),
        0.0,
        10000.0,
        (0.0, 10000.0),
        step=50.0,
    )
    only_sellable = st.checkbox(
        t("candidates.only_sellable"),
        value=(BD_WORKBENCH_PHASE >= 2),
        help=t("candidates.only_sellable_help"),
    )
    sort_mode = st.selectbox(
        t("candidates.sort_mode"),
        ["legacy_sps", "dual_model"],
        index=(1 if BD_WORKBENCH_PHASE >= 2 else 0),
        format_func=lambda x: t(f"candidates.sort.{x}"),
    )
    creator_types = st.multiselect(
        t("candidates.creator_type"),
        CREATOR_TYPE_OPTS,
        default=CREATOR_TYPE_OPTS,
        format_func=_opt("creator_type"),
    )
    strategy_filter = st.multiselect(
        t("candidates.strategy"),
        STRATEGY_OPTS,
        format_func=_opt("strategy"),
    )
    bd_status_filter = st.selectbox(
        t("candidates.bd_status"),
        BD_STATUS_OPTS,
        index=0,
        format_func=_opt("bd_status"),
    )

    st.markdown("---")
    per_page = st.selectbox(
        t("candidates.per_page"),
        [10, 20, 50, 100],
        index=1,
    )


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
    "character_consistency", "community_score", "audience_segment_score",
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

    ]
    for key, threshold, i18n_key in score_checks:
        val = c.get(key) or 0
        if val >= threshold:
            tags.append(f"✅ {t(i18n_key)}>{threshold}")

    monetization = c.get("monetization_score") or 0
    if monetization < 20:
        tags.append(f"⚠️ {t('candidates.sig_no_monetization')}")

    return " ".join(tags) if tags else "—"


# Compact source labels (align with product mock: L1: @seed / L1 Trend / Seed / Legacy)
_SOURCE_FORMAT = {
    "seed_following": "L1",
    "geo_explore": "L1 Geo",
    "hashtag_explore": "L1 Tag",
    "time_explore": "L1 Trend",
    "csv_import": "Seed",
    "legacy": "Legacy",
}


def _build_source(c: dict) -> str:
    """Format discovery source as compact L1 / strategy / Seed / Legacy."""
    strategy = (c.get("discovery_strategy") or "").strip()
    anchor = (c.get("anchor_seed") or "").strip()

    if strategy == "seed_following" and anchor:
        first_raw = anchor.split(",")[0].strip().lstrip("@")
        if len(first_raw) > 12:
            first_raw = first_raw[:11] + "…"
        extra_m = re.search(r"\(\+(\d+)\)\s*$", anchor)
        if extra_m:
            suffix = f" +{extra_m.group(1)}"
        else:
            parts = [p.strip() for p in anchor.split(",") if p.strip()]
            n_extra = max(0, len(parts) - 1)
            suffix = f" +{n_extra}" if n_extra else ""
        return f"L1: @{first_raw}{suffix}"

    label = _SOURCE_FORMAT.get(strategy, strategy or "—")
    return label


# ---------------------------------------------------------------------------
# Fragment: candidates table (query + render)
# ---------------------------------------------------------------------------

@st.fragment
def _render_candidates_table() -> None:
    """Render the full candidates table inside a fragment so that button clicks
    trigger only a local rerun instead of reloading the entire page."""

    where_sql, params = build_where_clauses(
        centrality=centrality_filter,
        creator_types=creator_types,
        strategy=strategy_filter,
        bd_status=bd_status_filter,
        sps_min=sps_min,
        sps_max=sps_max,
        sellability_min=sellability_min,
        sellability_max=sellability_max,
        pred_sales_min=pred_sales_min,
        pred_sales_max=pred_sales_max,
        only_sellable=only_sellable,
    )

    order_sql = (
        "cs.sps_score DESC"
        if sort_mode == "legacy_sps"
        else f"CASE WHEN COALESCE(cs.is_sellable, false) THEN COALESCE(cs.sps_score, 0) ELSE COALESCE(cs.sps_score, 0) * {NON_SELLABLE_SPS_WEIGHT} END DESC, COALESCE(cs.predicted_sales, 0) DESC, cs.sps_score DESC"
    )

    user = st.session_state.get("user", {})
    is_admin = user.get("role") == "admin"

    if is_admin:
        count_query = f"""
            SELECT COUNT(*) AS cnt
            FROM creators c
            JOIN creator_scores cs ON cs.creator_id = c.id
            LEFT JOIN creator_features cf ON cf.creator_id = c.id
            WHERE {where_sql}
        """
        total_row = fetch_one(count_query, tuple(params))
        total_count = total_row["cnt"] if total_row else 0

        page = st.session_state.get("candidates_page", 1)
        offset, total_pages = calc_pagination(total_count, page, per_page)

        query = f"""
            SELECT c.id, c.username, c.bio, c.followers, c.bd_status, c.bd_decision, c.bd_decision_note,
                   c.discovery_strategy, c.has_merch_experience, c.website,
                   c.anchor_seed, c.discovered_via, c.discovered_date,
                   c.creator_type_manual, c.creator_type_auto,
                   COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type,
                   cs.sellability_score, cs.is_sellable, cs.predicted_sales,
                   cs.sps_score, cs.centrality_tier, cs.seed_connections,
                   cf.audience_score, cf.engagement_score, cf.virality_score,
                   cf.posting_score, cf.monetization_score, cf.growth_score,
                   cf.character_consistency, cf.community_score
            FROM creators c
            JOIN creator_scores cs ON cs.creator_id = c.id
            LEFT JOIN creator_features cf ON cf.creator_id = c.id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT %s OFFSET %s
        """
        candidates = fetch_all(query, tuple(params) + (per_page, offset))
    else:
        bd_info = get_bd_distribution_info(user.get("id"))
        if bd_info is None:
            bd_count, bd_index = 1, 0
        else:
            bd_count, bd_index = bd_info

        count_query = build_assigned_count_sql(where_sql, order_sql, bd_count, bd_index)
        total_row = fetch_one(count_query, tuple(params))
        total_count = total_row["cnt"] if total_row else 0

        page = st.session_state.get("candidates_page", 1)
        offset, total_pages = calc_pagination(total_count, page, per_page)

        query = build_assigned_data_sql(where_sql, order_sql, bd_count, bd_index)
        candidates = fetch_all(query, tuple(params) + (per_page, offset))

    # -----------------------------------------------------------------------
    # Title + summary badges
    # -----------------------------------------------------------------------

    st.title(t("candidates.title"))

    hub_count = sum(1 for c in candidates if c.get("centrality_tier") == "Hub")
    conn_count = sum(1 for c in candidates if c.get("centrality_tier") == "Connector")
    high_sps_count = sum(1 for c in candidates if (c.get("sps_score") or 0) >= 75)
    high_sellability_count = sum(1 for c in candidates if (c.get("sellability_score") or 0) >= 60)
    high_pred_sales_count = sum(1 for c in candidates if (c.get("predicted_sales") or 0) >= 500)

    badge_cols = st.columns([2, 2, 2, 2, 2, 6])
    with badge_cols[0]:
        st.metric(label=t("options.centrality.Hub"), value=hub_count)
    with badge_cols[1]:
        st.metric(label=t("options.centrality.Connector"), value=conn_count)
    with badge_cols[2]:
        st.metric(label=t("candidates.badge_high_sps"), value=high_sps_count)
    with badge_cols[3]:
        st.metric(label=t("candidates.badge_high_sellability"), value=high_sellability_count)
    with badge_cols[4]:
        st.metric(label=t("candidates.badge_high_pred_sales"), value=high_pred_sales_count)
    with badge_cols[5]:
        st.markdown(f"**{t('candidates.match_count', count=total_count)}**")

    # -----------------------------------------------------------------------
    # Pagination controls (top)
    # -----------------------------------------------------------------------

    _render_pagination_controls(
        page=page, total_pages=total_pages, total_count=total_count, key_prefix="top"
    )

    st.markdown("---")

    # -----------------------------------------------------------------------
    # Table header
    # -----------------------------------------------------------------------

    header_cols = st.columns([2.1, 1.0, 0.9, 1.0, 0.7, 2.9, 1.0, 0.8, 2.6])
    header_cols[0].markdown(f"**{t('candidates.col_creator')}**")
    header_cols[1].markdown(f"**{t('candidates.centrality')}**")
    header_cols[2].markdown(f"**{t('candidates.col_sellability')}**")
    header_cols[3].markdown(f"**{t('candidates.col_pred_sales')}**")
    header_cols[4].markdown("**SPS**")
    header_cols[5].markdown(f"**{t('candidates.col_signals')}**")
    header_cols[6].markdown(f"**{t('candidates.col_source')}**")
    header_cols[7].markdown(f"**{t('candidates.col_discovered')}**")
    header_cols[8].markdown(f"**{t('candidates.col_actions')}**")
    st.markdown("---")

    if "candidates_detail_open_id" not in st.session_state:
        st.session_state.candidates_detail_open_id = None

    _RADAR_LABELS = [
        t("radar.audience"), t("radar.engagement"), t("radar.virality"),
        t("radar.posting"), t("radar.monetization"), t("radar.growth"),
        t("radar.character_consistency"), t("radar.community"),
        t("radar.audience_segment"),
    ]

    # -----------------------------------------------------------------------
    # Rows
    # -----------------------------------------------------------------------

    for c in candidates:
        cid = c["id"]
        tier = c.get("centrality_tier") or "Peripheral"
        emoji, _ = _TIER_STYLE.get(tier, ("⚪", "#95a5a6"))
        sps = float(c.get("sps_score") or 0)
        sellability = float(c.get("sellability_score") or 0)
        pred_sales = float(c.get("predicted_sales") or 0)
        signals = _build_signals(c)
        source = _build_source(c)
        disc_date = c.get("discovered_date")
        disc_str = disc_date.strftime("%m-%d") if disc_date else "—"

        row_cols = st.columns([2.1, 1.0, 0.9, 1.0, 0.7, 2.9, 1.0, 0.8, 2.6])
        row_cols[0].markdown(f"[@{c['username']}](https://x.com/{c['username']})")
        row_cols[1].markdown(f"{emoji} {t(f'options.centrality.{tier}')}")
        row_cols[2].markdown(f"**{sellability:.1f}**")
        row_cols[3].markdown(f"**{pred_sales:.0f}**")
        row_cols[4].markdown(f"**{sps:.1f}**")
        row_cols[5].markdown(signals)
        row_cols[6].caption(source)
        row_cols[7].caption(disc_str)

        current_decision = c.get("bd_decision")

        with row_cols[8]:
            act_cols = st.columns([1.1, 1, 1, 1])
            with act_cols[0]:
                _open = st.session_state.get("candidates_detail_open_id") == cid
                if st.button(
                    t("candidates.detail_toggle"),
                    key=f"detail_toggle_{cid}",
                    help=t("candidates.detail_radar"),
                ):
                    st.session_state.candidates_detail_open_id = None if _open else cid
                    st.rerun()
            with act_cols[1]:
                if current_decision == "interested":
                    st.markdown(
                        "<div style='background:#28a745;color:white;padding:4px 8px;border-radius:4px;font-size:14px;text-align:center;font-weight:600;'>✅</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button("✅", key=f"int_{cid}", help=t("candidates.btn_interested")):
                        with get_cursor() as cur:
                            cur.execute(
                                "UPDATE creators SET bd_decision = 'interested', bd_status = 'interested', last_bd_update = NOW() WHERE id = %s",
                                (cid,),
                            )
                        st.toast(t("candidates.marked_interested"))
                        st.rerun()
            with act_cols[2]:
                if current_decision == "rejected_unfit":
                    st.markdown(
                        "<div style='background:#dc3545;color:white;padding:4px 8px;border-radius:4px;font-size:14px;text-align:center;font-weight:600;'>🚫</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button("🚫", key=f"unfit_{cid}", help=t("candidates.btn_rejected_unfit")):
                        with get_cursor() as cur:
                            cur.execute(
                                "UPDATE creators SET bd_decision = 'rejected_unfit', bd_status = 'rejected_unfit', last_bd_update = NOW() WHERE id = %s",
                                (cid,),
                            )
                        st.toast(t("candidates.marked_rejected_unfit"))
                        st.rerun()
            with act_cols[3]:
                if current_decision == "rejected_not_creator":
                    st.markdown(
                        "<div style='background:#6c757d;color:white;padding:4px 8px;border-radius:4px;font-size:14px;text-align:center;font-weight:600;'>❌</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button("❌", key=f"notcr_{cid}", help=t("candidates.btn_rejected_not_creator")):
                        with get_cursor() as cur:
                            cur.execute(
                                "UPDATE creators SET bd_decision = 'rejected_not_creator', bd_status = 'rejected_not_creator', last_bd_update = NOW() WHERE id = %s",
                                (cid,),
                            )
                        st.toast(t("candidates.marked_rejected_not_creator"))
                        st.rerun()

        if st.session_state.get("candidates_detail_open_id") == cid:
            ctype = c.get("creator_type") or ""
            ctype_display = t(f"options.creator_type.{ctype}") if ctype else "N/A"
            followers_val = c.get("followers", 0) or 0
            seeds_val = c.get("seed_connections", 0) or 0
            with st.container(border=True):
                st.caption(t("candidates.detail_radar"))
                # 上：基础信息
                if c.get("bio"):
                    st.text(c["bio"][:500])
                else:
                    st.caption("—")
                st.markdown(
                    f"**{t('candidates.type_label')}**: {ctype_display} · "
                    f"**{t('candidates.followers_label')}**: {followers_val:,} · "
                    f"**{t('candidates.seed_connections_label')}**: {seeds_val}"
                )
                ncols = st.columns([4, 1])
                with ncols[0]:
                    note = st.text_input(
                        t("candidates.note_placeholder"),
                        key=f"note_{cid}",
                        placeholder=t("candidates.note_placeholder"),
                        value=c.get("bd_decision_note") or "",
                    )
                with ncols[1]:
                    if st.button(t("candidates.save_note"), key=f"note_save_{cid}"):
                        with get_cursor() as cur:
                            cur.execute("UPDATE creators SET bd_decision_note = %s WHERE id = %s", (note, cid))
                        st.toast(t("candidates.note_saved"))
                        st.rerun()
                current_type = c.get("creator_type_manual") or c.get("creator_type_auto") or "unknown"
                type_opts = CREATOR_TYPE_OPTS
                type_idx = type_opts.index(current_type) if current_type in type_opts else len(type_opts) - 1
                new_type = st.selectbox(
                    t("candidates.type_label"),
                    type_opts,
                    index=type_idx,
                    key=f"type_{cid}",
                    format_func=_opt("creator_type"),
                )
                if st.button(t("candidates.apply_type"), key=f"type_apply_{cid}"):
                    with get_cursor() as cur:
                        cur.execute(
                            "UPDATE creators SET creator_type_manual = %s WHERE id = %s",
                            (new_type, cid),
                        )
                    st.toast(t("candidates.type_updated"))
                    st.rerun()
                # 下：雷达图（整行宽度）
                st.markdown("---")
                features = {k: c.get(k, 0) for k in _FEATURE_KEYS}
                fig = create_radar_chart(features, f"@{c['username']}", labels=_RADAR_LABELS)
                st.plotly_chart(fig, use_container_width=True, key=f"radar_{cid}")

        st.markdown("<hr style='margin:2px 0;border-color:#333'>", unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # Pagination controls (bottom)
    # -----------------------------------------------------------------------

    st.markdown("---")
    _render_pagination_controls(
        page=page, total_pages=total_pages, total_count=total_count, key_prefix="bottom"
    )


# ---------------------------------------------------------------------------
# Render the fragment
# ---------------------------------------------------------------------------

_render_candidates_table()
