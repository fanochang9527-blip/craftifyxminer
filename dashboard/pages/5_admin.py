"""Page 5: Admin — 用户管理 + 登录审计日志。仅 Admin 角色可见。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from auth.session import require_login, require_role
from dashboard.i18n import t

user = require_login()
if not user:
    st.stop()
if not require_role("admin"):
    st.error(t("admin.admin_required"))
    st.stop()

import pandas as pd
from auth.password import hash_password, validate_complexity
from db.connection import fetch_all, get_cursor

st.title(t("admin.title"))

tab_users, tab_audit = st.tabs([t("admin.tab_users"), t("admin.tab_audit")])

with tab_users:
    users = fetch_all("SELECT id, username, display_name, role, is_active, failed_attempts, locked_until, last_login_at, created_at FROM users ORDER BY id")
    if users:
        st.dataframe(pd.DataFrame(users), use_container_width=True, hide_index=True)
    else:
        st.info(t("admin.no_users"))

    st.markdown("---")
    st.subheader(t("admin.add_user"))
    with st.form("add_user"):
        col1, col2 = st.columns(2)
        new_username = col1.text_input(t("admin.username"))
        new_display = col2.text_input(t("admin.display_name"))
        new_password = col1.text_input(t("admin.password"), type="password")
        new_role = col2.selectbox(
            t("admin.role"),
            ["bd", "admin"],
            format_func=lambda r: t(f"options.role.{r}"),
        )
        submitted = st.form_submit_button(t("admin.create_user"))

    if submitted and new_username and new_password:
        err = validate_complexity(new_password)
        if err:
            st.error(err)
        else:
            pw_hash = hash_password(new_password)
            try:
                with get_cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (username, password_hash, display_name, role) VALUES (%s, %s, %s, %s)",
                        (new_username, pw_hash, new_display or new_username, new_role),
                    )
                st.success(t("admin.user_created", username=new_username))
                st.rerun()
            except Exception as e:
                st.error(t("admin.create_failed", error=str(e)))

    st.markdown("---")
    st.subheader(t("admin.operations"))
    col_user, col_action = st.columns(2)
    target_user = col_user.text_input(t("admin.target_user"), key="op_target")
    action = col_action.selectbox(t("admin.action"), [
        t("admin.action_unlock"),
        t("admin.action_reset_pw"),
        t("admin.action_disable"),
        t("admin.action_enable"),
    ])
    new_pw = ""
    if action == t("admin.action_reset_pw"):
        new_pw = st.text_input(t("admin.new_password"), type="password", key="op_pw")

    if st.button(t("admin.execute")):
        if not target_user:
            st.warning(t("admin.enter_target"))
        elif action == t("admin.action_unlock"):
            with get_cursor() as cur:
                cur.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username = %s", (target_user,))
            st.success(t("admin.unlocked", username=target_user))
        elif action == t("admin.action_reset_pw"):
            err = validate_complexity(new_pw)
            if err:
                st.error(err)
            else:
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE users SET password_hash = %s, password_changed_at = NOW(), failed_attempts = 0, locked_until = NULL WHERE username = %s",
                        (hash_password(new_pw), target_user),
                    )
                st.success(t("admin.pw_reset", username=target_user))
        elif action == t("admin.action_disable"):
            with get_cursor() as cur:
                cur.execute("UPDATE users SET is_active = false WHERE username = %s", (target_user,))
            st.success(t("admin.disabled", username=target_user))
        elif action == t("admin.action_enable"):
            with get_cursor() as cur:
                cur.execute("UPDATE users SET is_active = true WHERE username = %s", (target_user,))
            st.success(t("admin.enabled", username=target_user))

with tab_audit:
    st.subheader(t("admin.recent_logins"))
    logs = fetch_all(
        "SELECT username, ip_address::text, success, user_agent, attempted_at FROM login_attempts ORDER BY attempted_at DESC LIMIT 100"
    )
    if logs:
        df_logs = pd.DataFrame(logs)
        df_logs["success"] = df_logs["success"].map({True: "✅", False: "❌"})
        st.dataframe(df_logs, use_container_width=True, hide_index=True)
    else:
        st.info(t("admin.no_logs"))
