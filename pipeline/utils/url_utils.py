"""URL normalization helpers for matching creator links across modules."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """标准化 URL 用于匹配比较。

    规则：
    - 去除首尾空白
    - 转小写
    - 移除尾部 /
    - 移除查询参数（如 ?s=21）和 fragment
    """
    if not url:
        return ""
    url = str(url).strip().lower()
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
        path = parsed.path.rstrip("/")
        url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    except Exception:
        url = url.rstrip("/").split("?")[0].split("#")[0]
    return url


# 通用 http/https URL
_HTTP_URL_RE = re.compile(
    r"https?://[^\s\n\r,，;；|<>\"{}\\^`\[\]）\)]+",
    re.IGNORECASE,
)

# 无协议的 X / Twitter 账号链接
_BARE_X_URL_RE = re.compile(
    r"\b(?:x\.com|twitter\.com)/[A-Za-z0-9_]+(?:\?[^\s\n\r,，;；|<>\"{}\\^`\[\]）\)]*)?",
    re.IGNORECASE,
)

# 提取末尾不属于 URL 的标点/单词
_TRAILING_JUNK_RE = re.compile(r"[.,;:!?\'\"）\)\]\}]+$")

# 常见平台名称（用于拆分粘连在 X URL 上的其他平台标签）
_PLATFORM_NAMES = [
    "facebook", "instagram", "youtube", "twitter", "twitch", "tiktok",
    "bsky", "bluesky", "tumblr", "patreon", "discord", "steam",
    "deviantart", "pixiv", "booth",
]

# X URL 路径中被粘连的平台名，如 x.com/n_kamuiinstagram -> x.com/n_kamui
_CONCATENATED_PLATFORM_IN_PATH_RE = re.compile(
    rf"((?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/[A-Za-z0-9_]+)({'|'.join(_PLATFORM_NAMES)})(?:[^A-Za-z0-9_]|$)",
    re.IGNORECASE,
)

# 查询参数尾部粘上的平台名，如 ?mx=2Facebook -> ?mx=2
_TRAILING_PLATFORM_IN_QUERY_RE = re.compile(
    rf"({'|'.join(_PLATFORM_NAMES)})[^\s/]*$",
    re.IGNORECASE,
)


def _ensure_https_for_x(link: str) -> str:
    """如果是 X / Twitter 的 http 链接，统一升级为 https。"""
    if re.match(r"^http://", link, re.IGNORECASE) and is_x_link(link):
        return "https" + link[4:]
    return link


def _extract_embedded_urls(link: str, start_pos: int = 0) -> list[str]:
    """从粘连 URL 字符串的指定位置之后，再挖出其它完整 URL（如 instagram.com/xxx）。"""
    results: list[str] = []
    # 用通用 HTTP 正则二次扫描，但只取已知平台的域名
    for m in _HTTP_URL_RE.finditer(link):
        if m.start() < start_pos:
            continue
        inner = m.group(0).strip()
        inner = _TRAILING_JUNK_RE.sub("", inner)
        if inner and get_platform(inner):
            results.append(_ensure_https_for_x(inner))
    return results


def _clean_extracted_link(link: str) -> list[str]:
    """清理单个提取出的链接，拆分粘连的平台标签，并统一 X 链接为 https。

    例如：
    - https://x.com/n_kamuiinstagram -> https://x.com/n_kamui
    - https://x.com/baimonbluewhale?mx=2Facebook -> https://x.com/baimonbluewhale?mx=2
    - http://x.com/user -> https://x.com/user
    """
    link = link.strip()
    if not link:
        return []

    results: list[str] = []

    # 1. 拆分路径中粘连的平台名：x.com/n_kamuiinstagram
    m = _CONCATENATED_PLATFORM_IN_PATH_RE.search(link)
    if m:
        cleaned = m.group(1).rstrip("/:?&")
        results.append(_ensure_https_for_x(cleaned))
        # 同时尝试把后续被粘连的其它平台 URL 也挖出来
        results.extend(_extract_embedded_urls(link, m.end()))
        return results

    # 2. 修剪查询参数尾部粘上的平台名
    trimmed = _TRAILING_PLATFORM_IN_QUERY_RE.sub("", link)
    if trimmed != link:
        trimmed = trimmed.rstrip("/:?&")
        if trimmed:
            results.append(_ensure_https_for_x(trimmed))
        return results

    return [_ensure_https_for_x(link)]


def extract_links(text: str | None) -> list[str]:
    """从文本中提取一个或多个 URL。

    原数据中存在 "Twitter: https://x.com/user"、"X(Twitter): https://x.com/userFacebook: ..."
    等自由格式，单纯按分隔符切分会把标签和 URL 混在一起。这里使用正则分别提取：
    1. 带 http/https 的 URL
    2. 不带协议的 x.com / twitter.com 账号链接
    """
    if not text:
        return []
    text = str(text).strip()
    if not text:
        return []

    links: list[str] = []
    seen: set[str] = set()

    # 1. 提取 http/https URL，并清理尾部可能混入的下一个标签
    for match in _HTTP_URL_RE.finditer(text):
        link = match.group(0).strip()
        link = _TRAILING_JUNK_RE.sub("", link)
        for cleaned in _clean_extracted_link(link):
            if cleaned and normalize_url(cleaned) not in seen:
                seen.add(normalize_url(cleaned))
                links.append(cleaned)

    # 2. 提取无协议的 X / Twitter 链接，并补齐 https://
    for match in _BARE_X_URL_RE.finditer(text):
        link = match.group(0).strip()
        link = _TRAILING_JUNK_RE.sub("", link)
        if link and not re.match(r"^https?://", link, re.IGNORECASE):
            link = "https://" + link
        for cleaned in _clean_extracted_link(link):
            if cleaned and normalize_url(cleaned) not in seen:
                seen.add(normalize_url(cleaned))
                links.append(cleaned)

    return links


# 常见平台域名识别（用于多平台判断）
_PLATFORM_DOMAINS = {
    "x": re.compile(r"(?:^|\.)x\.com$", re.IGNORECASE),
    "twitter": re.compile(r"(?:^|\.)twitter\.com$", re.IGNORECASE),
    "instagram": re.compile(r"(?:^|\.)instagram\.com$", re.IGNORECASE),
    "tiktok": re.compile(r"(?:^|\.)tiktok\.com$", re.IGNORECASE),
    "youtube": re.compile(r"(?:^|\.)youtube\.com$|(?:^|\.)youtu\.be$", re.IGNORECASE),
    "bsky": re.compile(r"(?:^|\.)bsky\.app$", re.IGNORECASE),
    "bluesky": re.compile(r"(?:^|\.)bsky\.app$", re.IGNORECASE),
    "tumblr": re.compile(r"(?:^|\.)tumblr\.com$", re.IGNORECASE),
    "facebook": re.compile(r"(?:^|\.)facebook\.com$|(?:^|\.)fb\.com$", re.IGNORECASE),
    "patreon": re.compile(r"(?:^|\.)patreon\.com$", re.IGNORECASE),
    "discord": re.compile(r"(?:^|\.)discord\.com$|(?:^|\.)discord\.gg$", re.IGNORECASE),
    "steam": re.compile(r"(?:^|\.)steam\.com$|(?:^|\.)steampowered\.com$", re.IGNORECASE),
    "deviantart": re.compile(r"(?:^|\.)deviantart\.com$", re.IGNORECASE),
    "pixiv": re.compile(r"(?:^|\.)pixiv\.net$", re.IGNORECASE),
    "booth": re.compile(r"(?:^|\.)booth\.pm$", re.IGNORECASE),
}


def get_platform(url: str) -> str | None:
    """根据 URL 域名判断所属平台，无法识别返回 None。"""
    if not url:
        return None
    try:
        parsed = urlsplit(str(url).strip())
        netloc = parsed.netloc.lower()
    except Exception:
        return None
    for platform, pattern in _PLATFORM_DOMAINS.items():
        if pattern.search(netloc):
            return platform
    return None


def is_x_link(url: str) -> bool:
    """判断是否为 X / Twitter 链接。"""
    platform = get_platform(url)
    return platform in ("x", "twitter")


# 直接扫描文本中平台域名/关键词（用于处理粘连导致 extract_links 丢失的平台信息）
_PLATFORM_DOMAIN_PATTERNS = {
    "instagram": re.compile(r"instagram\.com|ig:\s*https?://|instagram:\s*https?://", re.IGNORECASE),
    "facebook": re.compile(r"facebook\.com|fb\.com|m\.facebook", re.IGNORECASE),
    "youtube": re.compile(r"youtube\.com|youtu\.be", re.IGNORECASE),
    "twitch": re.compile(r"twitch\.tv", re.IGNORECASE),
    "tiktok": re.compile(r"tiktok\.com", re.IGNORECASE),
    "bsky": re.compile(r"bsky\.app|bluesky", re.IGNORECASE),
    "tumblr": re.compile(r"tumblr\.com", re.IGNORECASE),
    "patreon": re.compile(r"patreon\.com", re.IGNORECASE),
    "discord": re.compile(r"discord\.com|discord\.gg", re.IGNORECASE),
    "steam": re.compile(r"steampowered\.com|steam\.com", re.IGNORECASE),
    "deviantart": re.compile(r"deviantart\.com", re.IGNORECASE),
    "pixiv": re.compile(r"pixiv\.net", re.IGNORECASE),
    "booth": re.compile(r"booth\.pm", re.IGNORECASE),
}


def detect_platforms(text: str | None) -> set[str]:
    """从文本中识别所有出现的平台。

    同时使用 extract_links 和直接域名扫描，以应对 URL 粘连的情况。
    """
    if not text:
        return set()
    text = str(text)
    platforms: set[str] = set()

    # 1. 从提取到的链接判断平台
    for link in extract_links(text):
        platform = get_platform(link)
        if platform:
            platforms.add(platform)

    # 2. 直接扫描文本中的平台域名关键词
    for platform, pattern in _PLATFORM_DOMAIN_PATTERNS.items():
        if pattern.search(text):
            platforms.add(platform)

    # x 和 twitter 视为同一平台
    if "twitter" in platforms and "x" not in platforms:
        platforms.add("x")
        platforms.discard("twitter")

    return platforms
