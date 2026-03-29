"""Page 3: 联系追踪与销售反馈 — Interested 列表, 联系记录, GMV 录入, Seed 晋升。"""

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
from db.connection import fetch_all, get_cursor

st.title(t("outreach.title"))

_CHANNEL_OPTS = ["DM", "Email", "Discord", "Other"]


def _ch_fmt(v: str) -> str:
    return t(f"options.channel.{v}")


st.subheader(t("outreach.pending_contact"))
interested = fetch_all(
    """SELECT c.id, c.username, c.followers, cs.sps_score, cs.centrality_tier,
              (SELECT MAX(contacted_at) FROM outreach_log ol WHERE ol.creator_id = c.id) AS last_contact
       FROM creators c
       LEFT JOIN creator_scores cs ON cs.creator_id = c.id
       WHERE c.bd_decision = 'interested'
       ORDER BY cs.sps_score DESC NULLS LAST"""
)

if interested:
    st.dataframe(
        pd.DataFrame(interested),
        use_container_width=True,
        column_config={
            "username": st.column_config.TextColumn(t("outreach.col_username")),
            "sps_score": st.column_config.NumberColumn(t("outreach.col_sps"), format="%.1f"),
        },
    )
else:
    st.info(t("outreach.no_interested"))

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
                            "UPDATE creators SET is_seed = true, seed_tier = 'C' WHERE id = %s",
                            (creator_id,),
                        )
                        st.success(t("outreach.promoted", username=username))
            else:
                st.error(t("outreach.user_not_found", username=username))

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
