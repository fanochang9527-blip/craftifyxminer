"""Mimo API 客户端 — Anthropic 原生格式，支持 vision base64 输入。

作为 ContentStyleFilter 的 fallback 模型使用。
与 OpenAI 兼容接口不同，Mimo 需要：
- base64 编码的图片（不支持直接 URL）
- Anthropic 消息格式（system 为独立字段，messages 不含 system）
- x-api-key + anthropic-version header
"""

from __future__ import annotations

import base64
import logging

import httpx

from config.settings import MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL

logger = logging.getLogger(__name__)


class MimoClient:
    """Anthropic-compatible async client for Xiaomi MiMo API."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or MIMO_API_KEY
        self.model = model or MIMO_MODEL
        self.base_url = MIMO_BASE_URL
        self.provider = "mimo"

    async def chat(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 1024,
    ) -> dict:
        """Send a chat request to MiMo API.

        Args:
            system: System prompt (Anthropic puts this in a separate field).
            messages: Anthropic-format messages list.
            max_tokens: Max output tokens.

        Returns:
            {"content": str, "usage": dict, "_provider": str, "_model": str}
        """
        if not self.api_key or self.api_key == "tp-CHANGE_ME":
            raise RuntimeError("Mimo API key not configured")

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            # Extract text content (skip thinking blocks)
            text_content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text_content += block.get("text", "")

            usage = data.get("usage", {})
            total_tokens = (
                usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            )

            return {
                "content": text_content,
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": total_tokens,
                },
                "_provider": self.provider,
                "_model": self.model,
            }


async def download_image(url: str) -> bytes | None:
    """下载图片并返回二进制数据。"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.warning("Failed to download image %s: %s", url, e)
        return None


def build_mimo_vision_content(
    username: str,
    tweets: list[dict],
    max_media: int = 3,
    max_tweets: int = 5,
) -> tuple[list[dict], list[str]]:
    """构建 Anthropic vision 格式的 content blocks。

    Returns:
        (content_blocks, media_sample_urls)
    """
    content_blocks: list[dict] = []

    intro = f"分析以下 Twitter/X 创作者（@{username}）的作品风格。"
    tweet_texts: list[str] = []
    for tw in tweets:
        text = tw.get("text") or ""
        if text:
            tweet_texts.append(text)
    if tweet_texts:
        intro += "\n相关推文文本：\n" + "\n---\n".join(tweet_texts[:max_tweets])
    content_blocks.append({"type": "text", "text": intro})

    media_sample: list[str] = []
    media_count = 0

    for tw in tweets:
        urls = tw.get("media_urls") or []
        for url in urls:
            if media_count >= max_media:
                break
            img_data = download_image_sync(url)
            if img_data:
                content_type = _guess_content_type(url)
                b64 = base64.b64encode(img_data).decode("utf-8")
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": b64,
                    },
                })
                media_sample.append(url)
                media_count += 1
        if media_count >= max_media:
            break

    return content_blocks, media_sample


def download_image_sync(url: str) -> bytes | None:
    """同步下载图片（用于 fallback 路径中的数据准备）。"""
    try:
        import httpx

        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.warning("Failed to download image %s: %s", url, e)
        return None


def _guess_content_type(url: str) -> str:
    url_lower = url.lower()
    if url_lower.endswith(".png"):
        return "image/png"
    if url_lower.endswith(".gif"):
        return "image/gif"
    if url_lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"
