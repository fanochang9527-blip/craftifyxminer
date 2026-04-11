"""Page 3: 创作者池 + 联系追踪 + 销售反馈 + 模型健康度。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from auth.session import require_login

if not require_login():
    st.stop()

import pandas as pd
from datetime import date

from dashboard.i18n import t
from db.connection import fetch_all, fetch_one, get_cursor

st.title(t("outreach.title"))

_CHANNEL_OPTS = ["DM", "Email", "Discord", "Other"]


def _ch_fmt(v: str) -> str:
    return t(f"options.channel.{v}")


# ---------------------------------------------------------------------------
# Creator Pool — "interested" creators
# ---------------------------------------------------------------------------
st.subheader(t("outreach.pending_contact"))
interested = fetch_all(
    """SELECT c.id, c.username, c.followers,
              COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type,
              cs.sps_score, cs.centrality_tier,
              c.last_bd_update AS entry_time,
              (SELECT ol.bd_username FROM outreach_log ol
               WHERE ol.creator_id = c.id ORDER BY ol.contacted_at DESC LIMIT 1) AS bd_account,
              (SELECT MAX(ol.contacted_at) FROM outreach_log ol WHERE ol.creator_id = c.id) AS last_contact
       FROM creators c
       LEFT JOIN creator_scores cs ON cs.creator_id = c.id
       WHERE c.bd_decision = 'interested'
       ORDER BY cs.sps_score DESC NULLS LAST"""
)

if interested:
    df = pd.DataFrame(interested)
    df["homepage"] = df["username"].apply(lambda u: f"https://x.com/{u}")
    display_cols = [
        "id", "creator_type", "username", "homepage",
        "followers", "sps_score", "bd_account", "entry_time",
    ]
    existing_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[existing_cols],
        use_container_width=True,
        column_config={
            "id": st.column_config.NumberColumn(t("outreach.col_id"), width="small"),
            "creator_type": st.column_config.TextColumn(t("outreach.col_type")),
            "username": st.column_config.TextColumn(t("outreach.col_username")),
            "homepage": st.column_config.LinkColumn(t("outreach.col_homepage")),
            "followers": st.column_config.NumberColumn(t("outreach.col_followers"), format="%d"),
            "sps_score": st.column_config.NumberColumn(t("outreach.col_sps"), format="%.1f"),
            "bd_account": st.column_config.TextColumn(t("outreach.col_bd_account")),
            "entry_time": st.column_config.DatetimeColumn(t("outreach.col_entry_time")),
        },
    )
else:
    st.info(t("outreach.no_interested"))

# ---------------------------------------------------------------------------
# Model Health Card
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader(t("outreach.model_health"))
latest_eval = fetch_one(
    """SELECT * FROM model_evaluations
       ORDER BY evaluated_at DESC LIMIT 1"""
)
if latest_eval:
    mcols = st.columns(5)
    mcols[0].metric("Recall", f"{(latest_eval.get('recall') or 0) * 100:.1f}%")
    mcols[1].metric("Precision", f"{(latest_eval.get('precision_score') or 0) * 100:.1f}%")
    mcols[2].metric("F2-Score", f"{(latest_eval.get('f2_score') or 0) * 100:.1f}%")
    mcols[3].metric("P@250", f"{(latest_eval.get('precision_at_250') or 0) * 100:.1f}%")
    mcols[4].metric("Spearman", f"{latest_eval.get('spearman_corr') or 0:.3f}")
    st.caption(f"Model: {latest_eval.get('model_version', 'N/A')} | "
               f"Evaluated: {latest_eval.get('evaluated_at', 'N/A')}")
else:
    st.info("No model evaluation data yet.")

# ---------------------------------------------------------------------------
# Contact Log
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader(t("outreach.log_contact"))
with st.form("outreach_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        contact_username = st.text_input(t("outreach.creator_username"), placeholder="@username")
    with col2:
        channel = st.selectbox(t("outreach.channel"), _CHANNEL_OPTS, format_func=_ch_fmt)
    with col3:
        bd_username = st.text_input(t("outreach.bd_person"), placeholder="your_name")

    notes = st.text_area(t("outreach.notes"), placeholder=t("outreach.contact_detail"))
    submitted = st.form_submit_button(t("outreach.submit_contact"))

    if submitted and contact_username:
        username = contact_username.strip().lstrip("@").lower()
        with get_cursor() as cur:
            cur.execute("SELECT id FROM creators WHERE username = %s", (username,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    """INSERT INTO outreach_log
                           (creator_id, bd_username, contact_channel, contacted_at, notes)
                       VALUES (%s, %s, %s, NOW(), %s)""",
                    (row["id"], bd_username, channel, notes),
                )
                st.success(t("outreach.contact_recorded", username=username))
            else:
                st.error(t("outreach.user_not_found", username=username))

# ---------------------------------------------------------------------------
# Sales Feedback
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader(t("outreach.sales_feedback"))
with st.form("sales_form"):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        sales_username = st.text_input(t("outreach.creator_username"), placeholder="@username", key="sales_user")
    with col2:
        gmv = st.number_input(t("outreach.gmv"), min_value=0.0, step=100.0)
    with col3:
        units_sold = st.number_input(t("outreach.units_sold"), min_value=0, step=1)
    with col4:
        launch_date = st.date_input(t("outreach.launch_date"), value=date.today())

    sku_id = st.text_input(t("outreach.sku_id"))
    sales_submitted = st.form_submit_button(t("outreach.submit_sales"))

    if sales_submitted and sales_username:
        username = sales_username.strip().lstrip("@").lower()
        with get_cursor() as cur:
            cur.execute("SELECT id FROM creators WHERE username = %s", (username,))
            row = cur.fetchone()
            if row:
                creator_id = row["id"]
                cur.execute(
                    """INSERT INTO sales_feedback
                           (creator_id, sku_id, gmv, units_sold, launch_date)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (creator_id, sku_id or None, gmv, units_sold, launch_date),
                )
                st.success(t("outreach.sales_recorded", username=username, gmv=f"{gmv:,.2f}"))

                if gmv > 1000:
                    st.warning(t("outreach.promote_hint", username=username))
                    if st.button(t("outreach.promote_btn", username=username), key=f"promote_{creator_id}"):
                        cur.execute(
                            "UPDATE creators SET is_seed = true WHERE id = %s",
                            (creator_id,),
                        )
                        st.success(t("outreach.promoted", username=username))
            else:
                st.error(t("outreach.user_not_found", username=username))

# ---------------------------------------------------------------------------
# Completed Deals
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader(t("outreach.completed_deals"))
deals = fetch_all(
    """SELECT c.username, sf.gmv, sf.units_sold, sf.launch_date, sf.created_at
       FROM sales_feedback sf
       JOIN creators c ON c.id = sf.creator_id
       ORDER BY sf.created_at DESC
       LIMIT 50"""
)
if deals:
    st.dataframe(pd.DataFrame(deals), use_container_width=True)
else:
    st.info(t("outreach.no_deals"))
