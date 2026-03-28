"""Page 3: 联系追踪与销售反馈 — Interested 列表, 联系记录, GMV 录入, Seed 晋升。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import date

from db.connection import fetch_all, get_cursor

st.set_page_config(page_title="Outreach", layout="wide")
st.title("📞 联系追踪与销售反馈")

# --- Interested 创作者列表 ---
st.subheader("待联系创作者")
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
            "username": st.column_config.TextColumn("Username"),
            "sps_score": st.column_config.NumberColumn("SPS", format="%.1f"),
        },
    )
else:
    st.info("暂无 Interested 标记的创作者")

st.markdown("---")

# --- 录入联系记录 ---
st.subheader("📝 录入联系记录")
with st.form("outreach_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        contact_username = st.text_input("创作者 Username", placeholder="@username")
    with col2:
        channel = st.selectbox("联系渠道", ["DM", "Email", "Discord", "Other"])
    with col3:
        bd_username = st.text_input("BD 负责人", placeholder="your_name")

    notes = st.text_area("备注", placeholder="联系详情...")
    submitted = st.form_submit_button("提交联系记录")

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
                st.success(f"已记录对 @{username} 的联系")
            else:
                st.error(f"未找到用户 @{username}")

st.markdown("---")

# --- 销售反馈录入 ---
st.subheader("💰 销售反馈录入")
with st.form("sales_form"):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        sales_username = st.text_input("创作者 Username", placeholder="@username", key="sales_user")
    with col2:
        gmv = st.number_input("GMV ($)", min_value=0.0, step=100.0)
    with col3:
        units_sold = st.number_input("Units Sold", min_value=0, step=1)
    with col4:
        launch_date = st.date_input("Launch Date", value=date.today())

    sku_id = st.text_input("SKU ID (可选)")
    sales_submitted = st.form_submit_button("提交销售数据")

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
                st.success(f"已记录 @{username} 的销售数据 (GMV: ${gmv:,.2f})")

                # Seed 晋升提示
                if gmv > 1000:
                    st.warning(f"🌟 @{username} 的 GMV > $1,000，建议晋升为 Seed！")
                    if st.button(f"一键晋升 @{username} 为 Seed", key=f"promote_{creator_id}"):
                        cur.execute(
                            "UPDATE creators SET is_seed = true, seed_tier = 'C' WHERE id = %s",
                            (creator_id,),
                        )
                        st.success(f"@{username} 已晋升为 Seed (Tier C)")
            else:
                st.error(f"未找到用户 @{username}")

# --- 已完成交易 ---
st.markdown("---")
st.subheader("📋 已完成交易记录")
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
    st.info("暂无销售记录")
