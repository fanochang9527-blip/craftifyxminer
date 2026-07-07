#!/usr/bin/env python3
"""CraftifyX Miner — 综合数据统计报告生成器

包含：
1. 每日数据漏斗
2. 每日发现批次
3. 每日新增创作者及过滤状态
4. 每日分类统计
5. 每日成本追踪
6. 数据量与数据质量概览
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import fetch_all, fetch_one


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_table(headers: list[str], rows: list[list]):
    """Simple ASCII table printer."""
    if not rows:
        print("(无数据)")
        return
    cols = len(headers)
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    print(sep)
    print("| " + " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)) + " |")
    print(sep)
    for row in rows:
        print("| " + " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + " |")
    print(sep)


def daily_funnel():
    """1. 每日数据漏斗：基于 discovery_batches 和 creators 状态变化。"""
    section("1. 每日数据漏斗 (Daily Data Funnel)")
    rows = fetch_all("""
        SELECT
            db.batch_date,
            db.raw_discovered AS raw,
            db.after_ai_filter AS filtered,
            db.after_deep_scrape AS deep_scraped,
            COALESCE(nc.total_new, 0) AS creators_new,
            COALESCE(nc.passed, 0) AS creators_passed
        FROM discovery_batches db
        LEFT JOIN (
            SELECT
                discovered_date,
                COUNT(*) AS total_new,
                COUNT(*) FILTER (WHERE bd_status IN ('rule_passed', 'ai_passed')) AS passed
            FROM creators
            GROUP BY discovered_date
        ) nc ON nc.discovered_date = db.batch_date
        ORDER BY db.batch_date DESC
        LIMIT 30
    """)
    headers = ["日期", "原始发现", "AI过滤通过", "深度抓取", "新增创作者", "通过人数"]
    data = []
    for r in rows:
        data.append([
            r["batch_date"],
            r["raw"],
            r["filtered"],
            r["deep_scraped"],
            r["creators_new"],
            r["creators_passed"],
        ])
    print_table(headers, data)

    # Funnel rates
    print("\n  → 漏斗转化率（近30日均值）:")
    agg = fetch_one("""
        SELECT
            AVG(raw_discovered) AS avg_raw,
            AVG(after_ai_filter) AS avg_filtered,
            AVG(after_deep_scrape) AS avg_deep
        FROM discovery_batches
        WHERE batch_date >= CURRENT_DATE - INTERVAL '30 days'
    """)
    if agg and agg["avg_raw"]:
        raw = float(agg["avg_raw"] or 0)
        filtered = float(agg["avg_filtered"] or 0)
        deep = float(agg["avg_deep"] or 0)
        print(f"     原始发现 → AI过滤通过: {filtered/raw*100:.1f}%" if raw else "     N/A")
        print(f"     AI过滤通过 → 深度抓取: {deep/filtered*100:.1f}%" if filtered else "     N/A")


def daily_discovery_batches():
    """2. 每日发现批次详情。"""
    section("2. 每日发现批次 (Daily Discovery Batches)")
    rows = fetch_all("""
        SELECT
            batch_date,
            batch_type,
            array_length(anchor_seeds, 1) AS anchor_count,
            raw_discovered,
            after_ai_filter,
            after_deep_scrape,
            created_at
        FROM discovery_batches
        ORDER BY batch_date DESC, created_at DESC
        LIMIT 30
    """)
    headers = ["日期", "批次类型", "锚点数", "原始发现", "AI通过", "深度抓取", "创建时间"]
    data = []
    for r in rows:
        data.append([
            r["batch_date"],
            r["batch_type"],
            r["anchor_count"] or 0,
            r["raw_discovered"],
            r["after_ai_filter"],
            r["after_deep_scrape"],
            r["created_at"].strftime("%H:%M") if r["created_at"] else "",
        ])
    print_table(headers, data)


def daily_new_creators_and_filter_status():
    """3. 每日新增创作者及过滤状态。"""
    section("3. 每日新增创作者及过滤状态 (Daily New Creators & Filter Status)")
    rows = fetch_all("""
        SELECT
            discovered_date,
            COUNT(*) AS total_new,
            COUNT(*) FILTER (WHERE bd_status = 'pending') AS pending,
            COUNT(*) FILTER (WHERE bd_status = 'rule_passed') AS rule_passed,
            COUNT(*) FILTER (WHERE bd_status = 'rule_rejected') AS rule_rejected,
            COUNT(*) FILTER (WHERE bd_status = 'ai_passed') AS ai_passed,
            COUNT(*) FILTER (WHERE bd_status = 'ai_rejected') AS ai_rejected,
            COUNT(*) FILTER (WHERE bd_status = 'interested') AS interested,
            COUNT(*) FILTER (WHERE bd_status = 'rejected_unfit') AS rejected_unfit,
            COUNT(*) FILTER (WHERE bd_status IN ('rule_passed', 'ai_passed')) AS total_passed
        FROM creators
        GROUP BY discovered_date
        ORDER BY discovered_date DESC
        LIMIT 30
    """)
    headers = ["日期", "新增", "待审", "规则通过", "规则拒绝", "AI通过", "AI拒绝", "感兴趣", "不合适", "总通过"]
    data = []
    for r in rows:
        data.append([
            r["discovered_date"],
            r["total_new"],
            r["pending"],
            r["rule_passed"],
            r["rule_rejected"],
            r["ai_passed"],
            r["ai_rejected"],
            r["interested"],
            r["rejected_unfit"],
            r["total_passed"],
        ])
    print_table(headers, data)

    # 汇总过滤效率
    print("\n  → 整体过滤效率:")
    agg = fetch_one("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE bd_status = 'rule_passed') AS rp,
            COUNT(*) FILTER (WHERE bd_status = 'rule_rejected') AS rr,
            COUNT(*) FILTER (WHERE bd_status = 'ai_passed') AS ap,
            COUNT(*) FILTER (WHERE bd_status = 'ai_rejected') AS ar,
            COUNT(*) FILTER (WHERE bd_status IN ('rule_passed', 'ai_passed')) AS passed
        FROM creators
        WHERE bd_status NOT IN ('pending')
    """)
    if agg and agg["total"]:
        t = agg["total"]
        print(f"     规则过滤通过率: {agg['rp']/t*100:.1f}%")
        print(f"     规则过滤拒绝率: {agg['rr']/t*100:.1f}%")
        print(f"     AI过滤通过率:   {agg['ap']/t*100:.1f}%")
        print(f"     AI过滤拒绝率:   {agg['ar']/t*100:.1f}%")
        print(f"     总体通过/处理比: {agg['passed']/t*100:.1f}%")


def daily_category_stats():
    """4. 每日分类统计（按 creator_type_auto / manual）。"""
    section("4. 每日分类统计 (Daily Category Stats)")
    rows = fetch_all("""
        SELECT
            discovered_date,
            COALESCE(creator_type_auto, 'unknown') AS ctype,
            COUNT(*) AS cnt
        FROM creators
        WHERE creator_type_auto IS NOT NULL
        GROUP BY discovered_date, creator_type_auto
        ORDER BY discovered_date DESC, cnt DESC
        LIMIT 60
    """)
    headers = ["日期", "创作者类型", "数量"]
    data = [[r["discovered_date"], r["ctype"], r["cnt"]] for r in rows]
    print_table(headers, data)

    # 总体分类分布
    print("\n  → 创作者类型总体分布:")
    overall = fetch_all("""
        SELECT
            COALESCE(creator_type_auto, 'unknown') AS ctype,
            COUNT(*) AS cnt,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM creators
        GROUP BY creator_type_auto
        ORDER BY cnt DESC
    """)
    for r in overall:
        print(f"     {r['ctype']}: {r['cnt']} ({r['pct']}%)")


def daily_cost_tracking():
    """5. 每日成本追踪。"""
    section("5. 每日成本追踪 (Daily Cost Tracking)")
    rows = fetch_all("""
        SELECT
            date,
            apify_cost_usd,
            llm_cost_usd,
            proxy_cost_usd,
            total_cost_usd,
            llm_tokens_used,
            apify_cu_used,
            proxy_datacenter_gb,
            proxy_residential_gb
        FROM cost_tracking
        ORDER BY date DESC
        LIMIT 30
    """)
    headers = ["日期", "Apify($)", "LLM($)", "Proxy($)", "总计($)", "Tokens", "CU", "DC-GB", "Res-GB"]
    data = []
    for r in rows:
        data.append([
            r["date"],
            f"{r['apify_cost_usd']:.2f}",
            f"{r['llm_cost_usd']:.2f}",
            f"{r['proxy_cost_usd']:.2f}",
            f"{r['total_cost_usd']:.2f}",
            r["llm_tokens_used"] or 0,
            f"{r['apify_cu_used'] or 0:.1f}",
            f"{r['proxy_datacenter_gb'] or 0:.2f}",
            f"{r['proxy_residential_gb'] or 0:.2f}",
        ])
    print_table(headers, data)

    # 成本汇总
    print("\n  → 成本汇总:")
    agg = fetch_one("""
        SELECT
            SUM(total_cost_usd) AS total,
            SUM(apify_cost_usd) AS apify,
            SUM(llm_cost_usd) AS llm,
            SUM(proxy_cost_usd) AS proxy,
            SUM(llm_tokens_used) AS tokens,
            COUNT(DISTINCT date) AS days
        FROM cost_tracking
    """)
    if agg:
        print(f"     追踪天数: {agg['days']}")
        print(f"     总成本: ${agg['total']:.2f}")
        print(f"     Apify:  ${agg['apify']:.2f} ({agg['apify']/agg['total']*100:.1f}%)") if agg["total"] else None
        print(f"     LLM:    ${agg['llm']:.2f} ({agg['llm']/agg['total']*100:.1f}%)") if agg["total"] else None
        print(f"     Proxy:  ${agg['proxy']:.2f} ({agg['proxy']/agg['total']*100:.1f}%)") if agg["total"] else None
        print(f"     LLM Tokens: {agg['tokens']:,}")
        print(f"     日均成本: ${agg['total']/agg['days']:.2f}") if agg["days"] else None


def data_volume_and_quality():
    """6. 目前积累的数据量与数据质量。"""
    section("6. 数据量与数据质量 (Data Volume & Quality)")

    # 核心表数据量
    print("\n  [6.1] 核心数据表体量")
    tables = [
        ("creators", "创作者档案"),
        ("tweets", "推文数据"),
        ("creator_features", "特征工程"),
        ("creator_scores", "评分模型"),
        ("creator_graph", "关系图谱"),
        ("sales_feedback", "销售反馈"),
        ("outreach_log", "BD联系记录"),
        ("discovery_batches", "发现批次"),
    ]
    headers = ["表名", "中文名", "记录数"]
    data = []
    for table, name in tables:
        row = fetch_one(f"SELECT COUNT(*) AS cnt FROM {table}")
        data.append([table, name, row["cnt"] if row else 0])
    print_table(headers, data)

    # 数据完整性
    print("\n  [6.2] 数据完整性 (Completeness)")
    completeness = fetch_one("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE bio IS NOT NULL AND bio != '') AS has_bio,
            COUNT(*) FILTER (WHERE followers IS NOT NULL) AS has_followers,
            COUNT(*) FILTER (WHERE following IS NOT NULL) AS has_following,
            COUNT(*) FILTER (WHERE website IS NOT NULL AND website != '') AS has_website,
            COUNT(*) FILTER (WHERE creator_type_auto IS NOT NULL) AS has_type_auto,
            COUNT(*) FILTER (WHERE creator_type_manual IS NOT NULL) AS has_type_manual,
            COUNT(*) FILTER (WHERE discovery_strategy IS NOT NULL) AS has_strategy,
            COUNT(*) FILTER (WHERE discovered_date IS NOT NULL) AS has_date,
            COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM tweets t WHERE t.creator_id = creators.id)) AS has_tweets,
            COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM creator_features cf WHERE cf.creator_id = creators.id)) AS has_features,
            COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM creator_scores cs WHERE cs.creator_id = creators.id)) AS has_scores
        FROM creators
    """)
    if completeness:
        t = completeness["total"]
        headers = ["维度", "有数据", "占比"]
        data = [
            ["Bio", completeness["has_bio"], f"{completeness['has_bio']/t*100:.1f}%"],
            ["Followers", completeness["has_followers"], f"{completeness['has_followers']/t*100:.1f}%"],
            ["Following", completeness["has_following"], f"{completeness['has_following']/t*100:.1f}%"],
            ["Website", completeness["has_website"], f"{completeness['has_website']/t*100:.1f}%"],
            ["Type (Auto)", completeness["has_type_auto"], f"{completeness['has_type_auto']/t*100:.1f}%"],
            ["Type (Manual)", completeness["has_type_manual"], f"{completeness['has_type_manual']/t*100:.1f}%"],
            ["Strategy", completeness["has_strategy"], f"{completeness['has_strategy']/t*100:.1f}%"],
            ["Discovered Date", completeness["has_date"], f"{completeness['has_date']/t*100:.1f}%"],
            ["Tweets", completeness["has_tweets"], f"{completeness['has_tweets']/t*100:.1f}%"],
            ["Features", completeness["has_features"], f"{completeness['has_features']/t*100:.1f}%"],
            ["Scores", completeness["has_scores"], f"{completeness['has_scores']/t*100:.1f}%"],
        ]
        print_table(headers, data)

    # 粉丝分布
    print("\n  [6.3] 粉丝分布 (Audience Distribution)")
    audience = fetch_one("""
        SELECT
            AVG(followers) AS avg_followers,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY followers) AS median_followers,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY followers) AS p90_followers,
            MIN(followers) AS min_followers,
            MAX(followers) AS max_followers,
            COUNT(*) FILTER (WHERE followers >= 100000) AS over_100k,
            COUNT(*) FILTER (WHERE followers >= 10000 AND followers < 100000) AS over_10k,
            COUNT(*) FILTER (WHERE followers >= 1000 AND followers < 10000) AS over_1k,
            COUNT(*) FILTER (WHERE followers < 1000) AS under_1k
        FROM creators
        WHERE followers IS NOT NULL
    """)
    if audience:
        t = completeness["total"] if completeness else 1
        print(f"     平均粉丝: {audience['avg_followers']:,.0f}")
        print(f"     中位粉丝: {audience['median_followers']:,.0f}")
        print(f"     P90粉丝:  {audience['p90_followers']:,.0f}")
        print(f"     范围:     {audience['min_followers']:,.0f} ~ {audience['max_followers']:,.0f}")
        print(f"\n     分层分布:")
        print(f"       >100K:  {audience['over_100k']} ({audience['over_100k']/t*100:.1f}%)")
        print(f"       10K-100K: {audience['over_10k']} ({audience['over_10k']/t*100:.1f}%)")
        print(f"       1K-10K: {audience['over_1k']} ({audience['over_1k']/t*100:.1f}%)")
        print(f"       <1K:    {audience['under_1k']} ({audience['under_1k']/t*100:.1f}%)")

    # BD 决策分布
    print("\n  [6.4] BD 决策分布 (BD Decision Distribution)")
    bd = fetch_all("""
        SELECT bd_status, COUNT(*) AS cnt
        FROM creators
        GROUP BY bd_status
        ORDER BY cnt DESC
    """)
    headers = ["BD状态", "数量", "占比"]
    data = []
    total_creators = completeness["total"] if completeness else 1
    for r in bd:
        data.append([r["bd_status"], r["cnt"], f"{r['cnt']/total_creators*100:.1f}%"])
    print_table(headers, data)

    # Seed 质量
    print("\n  [6.5] Seed 创作者质量")
    seed_stats = fetch_one("""
        SELECT
            COUNT(*) FILTER (WHERE is_seed = true) AS seed_count,
            COUNT(*) FILTER (WHERE is_seed = false) AS non_seed_count,
            AVG(followers) FILTER (WHERE is_seed = true) AS seed_avg_followers,
            AVG(followers) FILTER (WHERE is_seed = false) AS non_seed_avg_followers
        FROM creators
    """)
    if seed_stats:
        print(f"     Seed 数量: {seed_stats['seed_count']}")
        print(f"     Seed 平均粉丝: {seed_stats['seed_avg_followers']:,.0f}")
        print(f"     非Seed平均粉丝: {seed_stats['non_seed_avg_followers']:,.0f}")

    # SPS / Sellability 分数分布
    print("\n  [6.6] 评分模型分布 (Score Distribution)")
    scores = fetch_one("""
        SELECT
            AVG(sps_score) AS avg_sps,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sps_score) AS median_sps,
            AVG(sellability_score) AS avg_sellability,
            COUNT(*) FILTER (WHERE is_sellable = true) AS sellable_count,
            COUNT(*) FILTER (WHERE is_sellable = false) AS not_sellable_count
        FROM creator_scores
    """)
    if scores:
        print(f"     SPS 平均分: {scores['avg_sps']:.1f}")
        print(f"     SPS 中位数: {scores['median_sps']:.1f}")
        print(f"     Sellability 平均分: {scores['avg_sellability']:.1f}")
        total_scored = (scores["sellable_count"] or 0) + (scores["not_sellable_count"] or 0)
        if total_scored > 0:
            print(f"     Sellable: {scores['sellable_count']} ({scores['sellable_count']/total_scored*100:.1f}%)")
            print(f"     Not Sellable: {scores['not_sellable_count']} ({scores['not_sellable_count']/total_scored*100:.1f}%)")


def main():
    print("CraftifyX Miner — 综合数据统计报告")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    daily_funnel()
    daily_discovery_batches()
    daily_new_creators_and_filter_status()
    daily_category_stats()
    daily_cost_tracking()
    data_volume_and_quality()

    print(f"\n{'=' * 60}")
    print("报告生成完毕")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
