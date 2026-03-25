"""Level 3 国产大模型 Bio 过滤 — 处理规则快筛未覆盖的灰区 BIO (~30%).

所有模型统一通过 OpenAI SDK 兼容接口调用，仅切换 base_url + api_key + model。
支持 Kimi K2.5 / Qwen3.5-Plus / DeepSeek / 智谱 GLM / MiniMax 五 provider。
利用长上下文 (256K) 一次批量处理 50 条 Bio。
"""

import asyncio
import json
import logging
from datetime import date

from openai import AsyncOpenAI

from config.settings import (
    FALLBACK_CHAIN,
    LLM_BATCH_SIZE,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    PROVIDER_CONFIGS,
    PROVIDER_MODELS,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert at identifying independent digital creators (illustrators, character designers, \
plush artists, VTuber designers, indie game devs, fan-artists, etc.) from their Twitter/X bio text.

Key signals of a real creator:
- Link DNA: linktr.ee, carrd.co, artstation, pixiv, booth.pm, vgen, etsy/shop, gumroad, ko-fi, patreon
- Identity words: illustrator, artist, character designer, 絵師, 画师, 插画师
- Action words: commission open, preorder, shop now, 接稿, 开预售
- Tool words: Procreate, Clip Studio, Blender, Live2D, Wacom
- Emoji clusters: 🎨🖌️✍️ (creative), 🛍️💰🛒 (commerce)

False positives to reject:
- Fan accounts, stan accounts, brand/agency/studio team accounts

For each bio, output:
  result: YES (creator) or NO (not a creator)
  type: one of oc_creator / vtuber / fan_artist / game_creator / content_creator
  confidence: 0.0–1.0
"""

BATCH_PROMPT_TEMPLATE = """\
Analyze the following {count} Twitter/X bios. For each, determine if the user is an independent \
digital creator. Return a JSON array with exactly {count} objects.

Bios:
{bios_json}

Return ONLY a JSON array (no markdown fences) like:
[{{"bio_id": 1, "result": "YES", "type": "oc_creator", "confidence": 0.92}}, ...]
"""


class LLMClient:
    """Unified async client for any OpenAI-compatible provider."""

    def __init__(self, provider: str):
        cfg = PROVIDER_CONFIGS.get(provider, {})
        self.provider = provider
        self.model = PROVIDER_MODELS.get(provider, "gpt-3.5-turbo")
        self._client = AsyncOpenAI(
            api_key=cfg.get("api_key", "sk-placeholder"),
            base_url=cfg.get("base_url", "https://api.openai.com/v1"),
        )

    async def chat(self, messages: list[dict], **kwargs) -> dict:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", LLM_TEMPERATURE),
            max_tokens=kwargs.get("max_tokens", LLM_MAX_TOKENS),
        )
        content = resp.choices[0].message.content or ""
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
            "total_tokens": resp.usage.total_tokens if resp.usage else 0,
        }
        return {"content": content, "usage": usage}


class AIFilter:
    """Level 3 AI filter with batch processing, fallback chain, and cost tracking."""

    def __init__(self, batch_size: int = LLM_BATCH_SIZE):
        self.batch_size = batch_size
        self._semaphore = asyncio.Semaphore(10)
        self._clients: dict[str, LLMClient] = {}
        # Freeze fallback order at construction time so tests/runtime are stable
        # even if module-level config is patched or reloaded later.
        self._fallback_chain = list(FALLBACK_CHAIN)
        for provider in self._fallback_chain:
            cfg = PROVIDER_CONFIGS.get(provider, {})
            if cfg.get("api_key"):
                self._clients[provider] = LLMClient(provider)

    def _get_client_chain(self) -> list[LLMClient]:
        return [self._clients[p] for p in self._fallback_chain if p in self._clients]

    async def _call_with_retry(self, messages: list[dict], max_retries: int = 3) -> dict:
        """Call LLM with exponential backoff and provider fallback."""
        clients = self._get_client_chain()
        if not clients:
            raise RuntimeError("No LLM providers configured with valid API keys")

        last_error: Exception | None = None
        for client in clients:
            for attempt in range(max_retries):
                try:
                    async with self._semaphore:
                        return await client.chat(messages)
                except Exception as e:
                    last_error = e
                    wait = 2 ** attempt
                    logger.warning(
                        "Provider %s attempt %d failed: %s. Retrying in %ds",
                        client.provider, attempt + 1, e, wait,
                    )
                    await asyncio.sleep(wait)
            logger.error("Provider %s exhausted retries, trying next", client.provider)

        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    async def _filter_one_batch(self, bio_batch: list[dict]) -> list[dict]:
        """Process a single batch of bios (up to batch_size)."""
        bios_for_prompt = [
            {"id": b["id"], "bio": b["bio"]} for b in bio_batch
        ]
        prompt = BATCH_PROMPT_TEMPLATE.format(
            count=len(bios_for_prompt),
            bios_json=json.dumps(bios_for_prompt, ensure_ascii=False),
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        resp = await self._call_with_retry(messages)
        self._track_cost(resp.get("usage", {}))

        content = resp["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            results = json.loads(content)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM response as JSON: %s", content[:200])
            results = [
                {"bio_id": b["id"], "result": "NO", "type": None, "confidence": 0.0}
                for b in bio_batch
            ]

        id_map = {b["id"]: b for b in bio_batch}
        normalized = []
        for r in results:
            bio_id = r.get("bio_id") or r.get("id")
            if bio_id not in id_map:
                continue
            normalized.append({
                "bio_id": bio_id,
                "result": r.get("result", "NO").upper(),
                "type": r.get("type"),
                "confidence": float(r.get("confidence", 0)),
            })

        seen_ids = {r["bio_id"] for r in normalized}
        for b in bio_batch:
            if b["id"] not in seen_ids:
                normalized.append({
                    "bio_id": b["id"],
                    "result": "NO",
                    "type": None,
                    "confidence": 0.0,
                })

        return normalized

    async def filter_batch(self, bios: list[dict]) -> list[dict]:
        """Filter a list of bios through the LLM.

        Args:
            bios: list of {"id": int, "bio": str}

        Returns:
            list of {"bio_id": int, "result": "YES"|"NO", "type": str, "confidence": float}
        """
        all_results: list[dict] = []
        batches = [
            bios[i : i + self.batch_size]
            for i in range(0, len(bios), self.batch_size)
        ]
        tasks = [self._filter_one_batch(batch) for batch in batches]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for br in batch_results:
            if isinstance(br, Exception):
                logger.error("Batch failed: %s", br)
                continue
            all_results.extend(br)

        return all_results

    def _track_cost(self, usage: dict) -> None:
        """Record token usage to cost_tracking table."""
        total = usage.get("total_tokens", 0)
        if not total:
            return
        try:
            from db.connection import upsert_cost
            estimated_cost = total * 0.000002  # conservative estimate
            upsert_cost(date.today(), llm_tokens_used=total, llm_cost_usd=estimated_cost)
        except Exception:
            logger.debug("Could not write cost tracking", exc_info=True)
