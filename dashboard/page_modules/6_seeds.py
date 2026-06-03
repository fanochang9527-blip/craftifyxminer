"""Page 6: 种子管理 — 筛选、列表、导出；仅 Admin 可 CSV/xlsx 导入（复用 pipeline.seed_import）。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

from auth.session import require_login
from dashboard.candidates_query import CREATOR_TYPE_OPTS, calc_pagination
from dashboard.i18n import t
from db.connection import fetch_all

if not require_login():
    st.stop()

user = st.session_state.get("user") or {}
is_admin = user.get("role") == "admin"

# 加载 .env（与 CLI seed_import 一致）
import config.settings  # noqa: F401


def _opt_creator_type(v: str) -> str:
    return t(f"options.creator_type.{v}")


def _build_where(
    *,
    is_seed_mode: str,
    creator_types: list[str],
    keyword: str,
) -> tuple[str, list]:
    clauses: list[str] = ["1=1"]
    params: list = []

    if is_seed_mode == "seeds_only":
        clauses.append("c.is_seed = true")
    elif is_seed_mode == "non_seeds":
        clauses.append("c.is_seed = false")

    if creator_types and len(creator_types) < len(CREATOR_TYPE_OPTS):
        clauses.append("COALESCE(c.creator_type_manual, c.creator_type_auto) = ANY(%s)")
        params.append(creator_types)

    kw = (keyword or "").strip()
    if kw:
        clauses.append("(c.username ILIKE %s OR COALESCE(c.bio, '') ILIKE %s)")
        like = f"%{kw}%"
        params.extend([like, like])

    return " AND ".join(clauses), params


st.title(t("seeds.title"))

with st.sidebar:
    st.header(t("seeds.filter_header"))
    is_seed_mode = st.radio(
        t("seeds.is_seed_label"),
        ["all", "seeds_only", "non_seeds"],
        format_func=lambda x: t(f"seeds.is_seed.{x}"),
        index=1,
    )
    creator_types = st.multiselect(
        t("seeds.creator_type_label"),
        CREATOR_TYPE_OPTS,
        default=CREATOR_TYPE_OPTS,
        format_func=_opt_creator_type,
    )
    keyword = st.text_input(t("seeds.keyword_label"), placeholder=t("seeds.keyword_placeholder"))
    per_page = st.selectbox(t("seeds.per_page"), [20, 50, 100, 200], index=1)

where_sql, params = _build_where(
    is_seed_mode=is_seed_mode,
    creator_types=creator_types,
    keyword=keyword,
)

count_row = fetch_all(
    f"SELECT COUNT(*) AS cnt FROM creators c WHERE {where_sql}",
    tuple(params),
)
total = int(count_row[0]["cnt"]) if count_row else 0

page = st.session_state.get("seeds_page", 1)
offset, total_pages = calc_pagination(total, page, per_page)

list_query = f"""
    SELECT c.id, c.username, c.is_seed, c.creator_type_manual, c.creator_type_auto,
           c.total_sales, c.discovery_strategy, c.first_seen_at, c.bio
    FROM creators c
    WHERE {where_sql}
    ORDER BY c.first_seen_at DESC NULLS LAST, c.id DESC
    LIMIT %s OFFSET %s
"""

rows = fetch_all(list_query, tuple(params) + (per_page, offset))

st.caption(t("seeds.match_count", count=total))

pag_cols = st.columns([3, 2, 2, 3])
with pag_cols[0]:
    st.caption(t("candidates.page_info", page=page, total_pages=total_pages, total=total))
with pag_cols[1]:
    if st.button("⬅️", disabled=(page <= 1), key="seeds_prev"):
        st.session_state["seeds_page"] = page - 1
        st.rerun()
with pag_cols[2]:
    if st.button("➡️", disabled=(page >= total_pages), key="seeds_next"):
        st.session_state["seeds_page"] = page + 1
        st.rerun()

if rows:
    display = []
    for r in rows:
        bio = r.get("bio") or ""
        if len(bio) > 120:
            bio = bio[:117] + "..."
        display.append(
            {
                t("seeds.col_id"): r["id"],
                t("seeds.col_username"): r["username"],
                t("seeds.col_is_seed"): r["is_seed"],
                t("seeds.col_creator_type_manual"): r.get("creator_type_manual"),
                t("seeds.col_creator_type_auto"): r.get("creator_type_auto"),
                t("seeds.col_total_sales"): r.get("total_sales"),
                t("seeds.col_discovery_strategy"): r.get("discovery_strategy"),
                t("seeds.col_first_seen"): r.get("first_seen_at"),
                t("seeds.col_bio"): bio,
            }
        )
    st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)
else:
    st.info(t("seeds.empty"))

# --- 导出（当前筛选，上限 EXPORT_CAP 行）---
EXPORT_CAP = 5000
export_rows = fetch_all(
    f"""
    SELECT c.id, c.username, c.is_seed, c.creator_type_manual, c.creator_type_auto,
           c.total_sales, c.discovery_strategy, c.first_seen_at, c.bio
    FROM creators c
    WHERE {where_sql}
    ORDER BY c.first_seen_at DESC NULLS LAST, c.id DESC
    LIMIT {EXPORT_CAP}
    """,
    tuple(params),
)
if export_rows:
    exp_df = pd.DataFrame(export_rows)
    csv_bytes = exp_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=t("seeds.export_csv"),
        data=csv_bytes,
        file_name="creators_seeds_export.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if total > EXPORT_CAP:
        st.caption(t("seeds.export_limit_note", n=EXPORT_CAP))

st.markdown("---")

# --- 仅 Admin：导入 ---
if is_admin:
    st.subheader(t("seeds.import_section"))
    st.caption(t("seeds.file_help"))
    up = st.file_uploader(
        t("seeds.file_uploader_label"),
        type=["csv", "xlsx", "xlsm"],
        key="seeds_upload",
    )
    skip_post = st.checkbox(t("seeds.skip_post_pipeline"), value=False)

    if st.button(t("seeds.import_button"), type="primary", key="seeds_do_import"):
        if not up:
            st.warning(t("seeds.import_no_file"))
        else:
            from pipeline.seed_import import import_seeds

            suffix = Path(up.name).suffix.lower() or ".csv"
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(up.getvalue())
                    tmp_path = tmp.name
                with st.spinner(t("seeds.import_running")):
                    result = import_seeds(tmp_path, skip_post_pipeline=skip_post)
                st.success(
                    t(
                        "seeds.import_ok",
                        total=result.get("total", 0),
                        inserted=result.get("inserted", 0),
                        updated=result.get("updated", 0),
                        suggestions=result.get("bio_rule_suggestions", 0),
                    )
                )
                ls = result.get("load_stats") or {}
                if ls:
                    def _dash(v: object) -> str:
                        return "—" if v is None else str(v)

                    st.caption(
                        t(
                            "seeds.import_load_stats",
                            source=ls.get("source", ""),
                            raw=ls.get("raw_rows", ""),
                            empty=_dash(ls.get("dropped_empty_handle")),
                            dedupe=_dash(ls.get("rows_after_dedupe")),
                            merged=_dash(ls.get("merged_duplicate_rows")),
                        )
                    )
            except Exception as e:
                st.error(t("seeds.import_err", error=str(e)))
            finally:
                if tmp_path and os.path.isfile(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
else:
    st.info(t("seeds.import_admin_only"))
