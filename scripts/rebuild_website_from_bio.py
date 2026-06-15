#!/usr/bin/env python3
"""存量清洗：从 bio 重新构建 creators.website。

执行步骤：
1. 清空所有 creators.website；
2. 从 bio 中提取 URL；
3. 过滤社交平台主页链接；
4. 优先保留店铺/商务链接，其次保留链接聚合页，最后保留第一个非社交链接；
5. 写回 creators.website；
6. 为受影响的创作者重新计算 creator_features（monetization_score / audience_segment_score 等）。

线上部署示例：
    python scripts/rebuild_website_from_bio.py --dry-run
    python scripts/rebuild_website_from_bio.py
    python scripts/rebuild_website_from_bio.py --skip-recompute  # 仅重建 website，不重新算特征
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from urllib.parse import urlparse

# 允许在无法连接真实 DB 的本地测试环境中被导入时优雅失败
try:
    from db.connection import fetch_all, get_cursor
    from pipeline.feature_engine import compute_features_for_creator
except Exception:  # pragma: no cover
    fetch_all = None  # type: ignore[assignment]
    get_cursor = None  # type: ignore[assignment]
    compute_features_for_creator = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 与 pipeline/creator_detail_sync.py 中的正则保持一致，覆盖 http(s) 与常见无协议域名
_URL_RE = re.compile(
    r"https?://[^\s<>\"'{}|\\^`\[\]]+|(?:www\.|[-a-zA-Z0-9]{2,}\.(?:com|co|net|org|io|cc|pm|jp|uk|de|fr|es|it|nl|be|ch|at|pl|se|no|dk|fi|ru|ua|tr|au|nz|br|ar|cl|co|sg|my|th|vn|id|ph|in|kr|cn|tw|hk|art|xyz|me|info|biz|dev|app|shop|store|studio|design|works))[^\s<>\"'{}|\\^`\[\]]*",
    re.IGNORECASE,
)

# 社交平台域名：这些链接会被过滤，不写入 creators.website
_SOCIAL_DOMAINS: frozenset[str] = frozenset(
    {
        # Twitter / X 生态
        "twitter.com",
        "x.com",
        "t.co",
        "twimg.com",
        # Meta
        "instagram.com",
        "facebook.com",
        "fb.me",
        "fb.com",
        "threads.net",
        "whatsapp.com",
        "wa.me",
        # 视频 / 直播
        "youtube.com",
        "youtu.be",
        "twitch.tv",
        "tiktok.com",
        "bilibili.com",
        "douyin.com",
        "kuaishou.com",
        "vimeo.com",
        "dailymotion.com",
        "kick.com",
        "rumble.com",
        # 社区 / 论坛
        "reddit.com",
        "discord.com",
        "discord.gg",
        "telegram.org",
        "t.me",
        "linkedin.com",
        "pinterest.com",
        "tumblr.com",
        "snapchat.com",
        "medium.com",
        "substack.com",
        # 国内社交
        "weibo.com",
        "weibo.cn",
        "qq.com",
        "weixin.qq.com",
        "zhihu.com",
        "jianshu.com",
        "xiaohongshu.com",
        "line.me",
        # 去中心化 / 替代平台
        "bluesky.social",
        "bsky.app",
        "mastodon.social",
        "mastodon.online",
        "pawoo.net",
        "baraag.net",
        "truth.social",
        "gab.com",
        "gettr.com",
        "parler.com",
        "minds.com",
        "hive.social",
        "cohost.org",
        "post.news",
        "counter.social",
        # 俄罗斯 / 东欧社交
        "vk.com",
        "ok.ru",
        # 音频
        "spotify.com",
        "soundcloud.com",
    }
)

# 店铺 / 商务平台：优先保留
_MERCH_DOMAINS: frozenset[str] = frozenset(
    {
        "booth.pm",
        "etsy.com",
        "gumroad.com",
        "gum.co",
        "patreon.com",
        "fanbox.cc",
        "ko-fi.com",
        "buymeacoffee.com",
        "vgen.co",
        "vgen.ai",
        "skeb.jp",
        "fiverr.com",
        "upwork.com",
        "bigcartel.com",
        "storenvy.com",
        "society6.com",
        "redbubble.com",
        "teepublic.com",
        "printful.com",
        "printify.com",
        "amazon.com",
        "amzn.to",
        "aliexpress.com",
        "taobao.com",
        "tmall.com",
        "jd.com",
        "shopify.com",
        "myshopify.com",
        "wix.com",
        "squarespace.com",
        "weebly.com",
        "bigcommerce.com",
        "ecwid.com",
        "paypal.me",
        "stripe.com",
        "lemonsqueezy.com",
        "lemon-squeezy.com",
        "itch.io",
        "gamejolt.com",
    }
)

# 链接聚合页：不是店铺，但通常指向店铺/作品集，优先级次于 _MERCH_DOMAINS
_LINK_AGGREGATOR_DOMAINS: frozenset[str] = frozenset(
    {
        "linktr.ee",
        "linktree.com",
        "carrd.co",
        "carrd.me",
        "lit.link",
        "taplink.cc",
        "allmylinks.com",
        "solo.to",
        "bio.link",
        "mssg.me",
    }
)

# 作品集平台：保留，但优先级最低
_PORTFOLIO_DOMAINS: frozenset[str] = frozenset(
    {
        "artstation.com",
        "behance.net",
        "deviantart.com",
        "pixiv.net",
        "pixiv.me",
        "toyhou.se",
    }
)


def _normalize_url(raw: str) -> str:
    raw = raw.rstrip(".,;:!?")
    if not raw.startswith("http"):
        raw = "https://" + raw
    return raw.lower()


def extract_links(bio: str | None) -> list[str]:
    """从 bio 文本中提取所有 URL，去重，按出现顺序返回。"""
    if not bio:
        return []
    seen: set[str] = set()
    links: list[str] = []
    for match in _URL_RE.finditer(bio):
        url = _normalize_url(match.group(0))
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _domain_match(url: str, domains: frozenset[str]) -> bool:
    """检查 URL 的 netloc 是否命中给定域名集合（支持子域）。"""
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return False
    if not netloc:
        return False
    # 去掉 www. / m. 等常见前缀后再匹配
    stripped = netloc
    for prefix in ("www.", "m.", "shop.", "store."):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
    return any(d in stripped for d in domains)


def is_social_url(url: str) -> bool:
    return _domain_match(url, _SOCIAL_DOMAINS)


def is_merch_url(url: str) -> bool:
    return _domain_match(url, _MERCH_DOMAINS)


def is_link_aggregator_url(url: str) -> bool:
    return _domain_match(url, _LINK_AGGREGATOR_DOMAINS)


def is_portfolio_url(url: str) -> bool:
    return _domain_match(url, _PORTFOLIO_DOMAINS)


def pick_website(links: list[str]) -> str | None:
    """从候选链接中挑选最合适的写入 creators.website。

    优先级：店铺/商务链接 > 链接聚合页 > 作品集 > 其他非社交平台链接
    """
    if not links:
        return None

    non_social = [u for u in links if not is_social_url(u)]
    if not non_social:
        return None

    for predicate in (is_merch_url, is_link_aggregator_url, is_portfolio_url):
        for url in non_social:
            if predicate(url):
                return url

    return non_social[0]


def _recompute_features_for(creator_ids: list[int]) -> tuple[int, int]:
    """为指定创作者重新计算 creator_features。"""
    if compute_features_for_creator is None:
        logger.warning("compute_features_for_creator unavailable, skipping recomputation")
        return 0, len(creator_ids)

    success = 0
    failed = 0
    for cid in creator_ids:
        try:
            compute_features_for_creator(cid)
            success += 1
        except Exception:
            logger.exception("Failed to recompute features for creator_id=%s", cid)
            failed += 1
    return success, failed


def rebuild_website_from_bio(
    *, dry_run: bool = False, recompute: bool = True, batch_size: int = 500
) -> dict:
    """一键执行存量清洗。

    Returns:
        {"cleared": int, "updated": int, "unchanged": int, "recomputed": (success, failed)}
    """
    if fetch_all is None or get_cursor is None:
        raise RuntimeError("Database connection not available")

    logger.info("Step 1/4: Fetching creators with bio...")
    rows = fetch_all(
        """SELECT id, username, bio, website
           FROM creators
           WHERE bio IS NOT NULL AND bio != ''
           ORDER BY id"""
    )
    logger.info("Found %d creators with non-empty bio", len(rows))

    # 先清空所有 website
    logger.info("Step 2/4: Clearing creators.website...")
    if not dry_run:
        with get_cursor() as cur:
            cur.execute("UPDATE creators SET website = ''")
    logger.info("Cleared creators.website (dry_run=%s)", dry_run)

    # 从 bio 提取并挑选 website
    logger.info("Step 3/4: Rebuilding website from bio links...")
    updates: list[tuple[str, int]] = []
    affected_creator_ids: list[int] = []
    unchanged = 0

    for r in rows:
        cid = r["id"]
        old_website = (r.get("website") or "").strip().lower()
        bio = r.get("bio") or ""

        links = extract_links(bio)
        new_website = pick_website(links)
        new_website_str = (new_website or "").strip()

        if new_website_str == old_website:
            unchanged += 1
            continue

        updates.append((new_website_str, cid))
        affected_creator_ids.append(cid)

    logger.info(
        "Prepared %d updates, %d unchanged (dry_run=%s)",
        len(updates),
        unchanged,
        dry_run,
    )

    if not dry_run and updates:
        with get_cursor() as cur:
            cur.executemany(
                "UPDATE creators SET website = %s WHERE id = %s",
                updates,
            )
        logger.info("Updated %d creators.website rows", len(updates))

    # 重新计算 features
    recompute_result = (0, 0)
    if recompute and affected_creator_ids and not dry_run:
        logger.info("Step 4/4: Recomputing features for %d affected creators...", len(affected_creator_ids))
        recompute_result = _recompute_features_for(affected_creator_ids)
        logger.info("Recomputed features: success=%d, failed=%d", *recompute_result)
    else:
        logger.info(
            "Step 4/4: Skipping feature recomputation (recompute=%s, affected=%d, dry_run=%s)",
            recompute,
            len(affected_creator_ids),
            dry_run,
        )

    return {
        "cleared": len(rows) if not dry_run else 0,
        "updated": len(updates) if not dry_run else 0,
        "unchanged": unchanged,
        "recomputed": {"success": recompute_result[0], "failed": recompute_result[1]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild creators.website from bio links and recompute features."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to database.",
    )
    parser.add_argument(
        "--skip-recompute",
        action="store_true",
        help="Only rebuild website, do not recompute creator_features.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for processing (currently used for logging only).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    stats = rebuild_website_from_bio(
        dry_run=args.dry_run,
        recompute=not args.skip_recompute,
        batch_size=args.batch_size,
    )
    logger.info("Done: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
