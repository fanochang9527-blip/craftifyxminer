"""多模态内容风格过滤 — 基于创作者推文图片判定写实风格与固定 IP。

位置: Deep Scrape 之后, Type Classification / Feature Engine 之前.
支持独立配置 provider / model, 便于后续 AB 测试 (如 mimo vs kimi).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date

from psycopg2.extras import Json as _Psycopg2Json

from config.settings import (
    CONTENT_STYLE_ENABLED,
    CONTENT_STYLE_LLM_PROVIDER,
    CONTENT_STYLE_LLM_MODEL,
    CONTENT_STYLE_MAX_MEDIA_PER_CREATOR,
    CONTENT_STYLE_MAX_TWEETS_PER_CREATOR,
    CONTENT_STYLE_CONFIDENCE_THRESHOLD,
    CONTENT_STYLE_BATCH_SIZE,
    CONTENT_STYLE_FALLBACK_CHAIN,
    PROVIDER_CONFIGS,
    PROVIDER_MODELS,
)
from db.connection import fetch_all, get_cursor, upsert_cost
from pipeline.ai_filter import (
    LLMClient,
    _RateLimiter,
    _is_non_retryable_auth_error,
    _is_overloaded_or_ratelimit,
)
from pipeline.mimo_client import MimoClient, build_mimo_vision_content

logger = logging.getLogger(__name__)

# 与 bio AI filter 共享全局 RPM 限流器（同一厂商 API）
_rate_limiter = _RateLimiter(rpm=150)

SYSTEM_PROMPT = """\
你是一个专业的视觉内容分析师，擅长分析 Twitter/X 创作者的作品风格。

这些创作者的作品将被评估是否适合制作成毛绒娃娃（plush toy）进行售卖。

你需要根据提供的图片和推文文本，判断以下两个问题：
1. 该创作者的作品是否为写实风格（realistic style）？写实风格指接近真实照片质感的绘画或渲染。注意：写实风格的作品不适合制作毛绒娃娃（会导致恐怖谷效应、销量差），应标记 is_realistic=true；而卡通、Q版、二次元、简化风格更适合毛绒娃娃，应标记 is_realistic=false。
2. 该创作者是否有固定 IP（fixed / recurring character）？即同一个原创角色形象是否多次出现在不同的作品中。拥有固定角色的创作者非常适合持续推出周边毛绒娃娃，应标记 has_fixed_ip=true。

请返回严格的 JSON 格式，不要包含 markdown 代码块：
{"is_realistic": true/false, "has_fixed_ip": true/false, "confidence": 0.0-1.0, "reason": "简短理由"}
"""


class ContentStyleFilter:
    """多模态内容风格过滤器。

    每个创作者独立发一次 LLM 请求（因含多张图片，不宜批量合并多个创作者）。
    """

    def __init__(self):
        self.batch_size = CONTENT_STYLE_BATCH_SIZE
        self.max_media = CONTENT_STYLE_MAX_MEDIA_PER_CREATOR
        self.max_tweets = CONTENT_STYLE_MAX_TWEETS_PER_CREATOR
        self.confidence_threshold = CONTENT_STYLE_CONFIDENCE_THRESHOLD
        self._semaphore = asyncio.Semaphore(3)
        self._clients: dict[str, LLMClient] = {}

        # 独立的 provider / model 配置，便于 AB 测试
        self._provider = CONTENT_STYLE_LLM_PROVIDER
        self._model = CONTENT_STYLE_LLM_MODEL or PROVIDER_MODELS.get(
            self._provider, "kimi-k2.5"
        )
        self._fallback_chain = list(CONTENT_STYLE_FALLBACK_CHAIN)

        for provider in self._fallback_chain:
            cfg = PROVIDER_CONFIGS.get(provider, {})
            key = cfg.get("api_key", "")
            if key and "CHANGE_ME" not in key and key != "sk-placeholder":
                self._clients[provider] = LLMClient(provider)

    # ------------------------------------------------------------------
    # LLM 调用（复用 ai_filter 的 retry + fallback 逻辑）
    # ------------------------------------------------------------------

    def _get_client_chain(self) -> list[LLMClient]:
        return [self._clients[p] for p in self._fallback_chain if p in self._clients]

    async def _call_with_retry(self, messages: list[dict], max_retries: int = 4) -> dict:
        clients = self._get_client_chain()
        if not clients:
            raise RuntimeError("No LLM providers configured for content style filter")

        last_error: Exception | None = None
        for client in clients:
            for attempt in range(max_retries):
                try:
                    async with self._semaphore:
                        await _rate_limiter.acquire()
                        resp = await client.chat(messages)
                        # 附加实际使用的 provider/model，供上层记录
                        resp["_provider"] = client.provider
                        resp["_model"] = client.model
                        return resp
                except Exception as e:
                    last_error = e
                    if _is_non_retryable_auth_error(e):
                        logger.warning(
                            "ContentStyle provider %s auth denied, trying next",
                            client.provider,
                        )
                        break
                    if _is_overloaded_or_ratelimit(e):
                        wait = (attempt + 1) * 10
                    else:
                        wait = 2 ** attempt
                    logger.warning(
                        "ContentStyle provider %s attempt %d/%d failed: %s. Retrying in %ds",
                        client.provider,
                        attempt + 1,
                        max_retries,
                        e,
                        wait,
                    )
                    await asyncio.sleep(wait)
            else:
                logger.error(
                    "ContentStyle provider %s exhausted retries, trying next",
                    client.provider,
                )
                continue

        raise RuntimeError(f"All content style providers failed. Last error: {last_error}")

    # ------------------------------------------------------------------
    # Prompt 组装
    # ------------------------------------------------------------------

    def _build_messages(self, username: str, tweets: list[dict]) -> list[dict]:
        """构建 OpenAI vision 格式的 messages。"""
        media_items: list[tuple[str, str]] = []  # (url, type)
        tweet_texts: list[str] = []

        for tw in tweets:
            text = tw.get("text") or ""
            if text:
                tweet_texts.append(text)

            urls = tw.get("media_urls") or []
            types = tw.get("media_types") or []
            for url, mtype in zip(urls, types):
                if url:
                    media_items.append((url, mtype))

            if len(media_items) >= self.max_media:
                break

        media_items = media_items[: self.max_media]

        # 组装多模态 content
        content: list[dict] = []
        intro = f"分析以下 Twitter/X 创作者（@{username}）的作品风格。"
        if tweet_texts:
            intro += "\n相关推文文本：\n" + "\n---\n".join(tweet_texts[: self.max_tweets])
        content.append({"type": "text", "text": intro})

        for url, mtype in media_items:
            # 视频当前使用预览图（poster）作为代理；二期可替换为抽帧图
            content.append({
                "type": "image_url",
                "image_url": {"url": url},
            })

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

    # ------------------------------------------------------------------
    # 结果解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_result(text: str) -> dict | None:
        text = text.strip()
        if not text:
            return None

        # 去掉 markdown fence
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 兜底：从文本中尝试提取最外层 JSON 对象
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None

    # ------------------------------------------------------------------
    # 成本追踪
    # ------------------------------------------------------------------

    @staticmethod
    def _track_cost(usage: dict) -> None:
        total = usage.get("total_tokens", 0)
        if not total:
            return
        try:
            estimated_cost = total * 0.000002
            upsert_cost(date.today(), llm_tokens_used=total, llm_cost_usd=estimated_cost)
        except Exception:
            logger.debug("Could not write cost tracking for content style", exc_info=True)

    # ------------------------------------------------------------------
    # 单创作者分析
    # ------------------------------------------------------------------

    async def _analyze_one(self, creator: dict) -> dict:
        creator_id = creator["id"]
        username = creator["username"]

        # 查询该创作者最近的有媒体推文（同步查询，数据量极小）
        tweets = fetch_all(
            """SELECT text, media_urls, media_types, created_at
               FROM tweets
               WHERE creator_id = %s
                 AND media_urls IS NOT NULL
                 AND array_length(media_urls, 1) > 0
               ORDER BY created_at DESC
               LIMIT %s""",
            (creator_id, self.max_tweets),
        )

        if not tweets:
            return {
                "creator_id": creator_id,
                "status": "skipped_no_media",
                "is_realistic": None,
                "has_fixed_ip": None,
                "confidence": 0.0,
                "model_used": None,
            }

        # ------------------------------------------------------------------
        # Step 1: 尝试主模型（OpenAI 兼容链 — Kimi / DeepSeek / DashScope）
        # ------------------------------------------------------------------
        primary_result = await self._try_primary_model(creator_id, username, tweets)
        if primary_result is not None:
            return primary_result

        # 主模型 API 调用异常 → 立即发出预警日志
        logger.error(
            "ALERT: Primary model (OpenAI-compatible) API call failed for creator %d (@%s). "
            "Falling back to Mimo. Please check API key validity, rate limits, and network connectivity.",
            creator_id, username,
        )

        # ------------------------------------------------------------------
        # Step 2: Fallback 到备选模型（Mimo — Anthropic 格式 + base64）
        # ------------------------------------------------------------------
        fallback_result = await self._try_fallback_mimo(creator_id, username, tweets)
        if fallback_result is not None:
            return fallback_result

        # ------------------------------------------------------------------
        # Step 3: 备选也失败 — 记录最终失败日志
        # ------------------------------------------------------------------
        logger.error(
            "CRITICAL: Both primary and fallback (Mimo) models failed for creator %d (@%s). "
            "Content style analysis could not be completed.",
            creator_id, username,
        )
        return {
            "creator_id": creator_id,
            "status": "failed",
            "is_realistic": None,
            "has_fixed_ip": None,
            "confidence": 0.0,
            "model_used": None,
        }

    # ------------------------------------------------------------------
    # 主模型（OpenAI 兼容）
    # ------------------------------------------------------------------

    async def _try_primary_model(self, creator_id: int, username: str, tweets: list[dict]) -> dict | None:
        """尝试 OpenAI 兼容的主模型链。

        Returns:
            dict: 分析结果（成功或解析失败均返回，不 fallback）
            None: API 调用异常，需要 fallback 到备选模型
        """
        messages = self._build_messages(username, tweets)
        try:
            resp = await self._call_with_retry(messages)
            self._track_cost(resp.get("usage", {}))
        except Exception as e:
            logger.warning(
                "Primary model chain API call failed for creator %d: %s",
                creator_id, e,
            )
            return None  # API 异常 → 触发 fallback

        provider = resp.get("_provider", self._provider)
        model = resp.get("_model", self._model)
        model_used = f"{provider}/{model}"

        parsed = self._parse_result(resp.get("content", ""))
        if parsed is None:
            # API 调用成功但内容不可解析 → 记录为 failed，不再 fallback
            # （fallback 到另一模型用相同 prompt 大概率也是同样格式）
            logger.warning(
                "Primary model returned unparseable result for creator %d: %s",
                creator_id, resp.get("content", "")[:200],
            )
            return {
                "creator_id": creator_id,
                "status": "failed",
                "is_realistic": None,
                "has_fixed_ip": None,
                "confidence": 0.0,
                "model_used": model_used,
            }

        return self._build_result(creator_id, tweets, parsed, model_used)

    # ------------------------------------------------------------------
    # 备选模型（Mimo — Anthropic）
    # ------------------------------------------------------------------

    async def _try_fallback_mimo(self, creator_id: int, username: str, tweets: list[dict]) -> dict | None:
        """尝试 Mimo 备选模型。成功返回结果，失败返回 None。"""
        from config.settings import MIMO_API_KEY

        if not MIMO_API_KEY or "CHANGE_ME" in MIMO_API_KEY:
            logger.debug("Mimo API key not configured, skipping fallback")
            return None

        try:
            content_blocks, media_sample = build_mimo_vision_content(
                username, tweets, max_media=self.max_media, max_tweets=self.max_tweets
            )
            if not any(b.get("type") == "image" for b in content_blocks):
                logger.debug("No images available for mimo fallback, skipping")
                return None

            mimo = MimoClient()
            resp = await mimo.chat(
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content_blocks}],
                max_tokens=1024,
            )
            self._track_cost(resp.get("usage", {}))
        except Exception as e:
            logger.warning("Mimo fallback failed for creator %d: %s", creator_id, e)
            return None

        model_used = f"{resp.get('_provider')}/{resp.get('_model')}"
        parsed = self._parse_result(resp.get("content", ""))
        if parsed is None:
            logger.warning(
                "Mimo returned unparseable result for creator %d: %s",
                creator_id, resp.get("content", "")[:200],
            )
            return None

        return self._build_result(creator_id, tweets, parsed, model_used, media_sample=media_sample)

    # ------------------------------------------------------------------
    # 结果组装
    # ------------------------------------------------------------------

    def _build_result(
        self,
        creator_id: int,
        tweets: list[dict],
        parsed: dict,
        model_used: str,
        media_sample: list[str] | None = None,
    ) -> dict:
        """从解析后的 JSON 组装最终结果。"""
        is_realistic = bool(parsed.get("is_realistic"))
        has_fixed_ip = bool(parsed.get("has_fixed_ip"))
        confidence = float(parsed.get("confidence", 0))
        reason = str(parsed.get("reason", ""))

        # 判定逻辑：非写实风格 + 固定IP + 置信度 >= 阈值
        passed = (not is_realistic) and has_fixed_ip and confidence >= self.confidence_threshold

        if media_sample is None:
            media_sample = []
            for tw in tweets:
                urls = tw.get("media_urls") or []
                media_sample.extend(urls)
                if len(media_sample) >= self.max_media:
                    break
            media_sample = media_sample[: self.max_media]

        return {
            "creator_id": creator_id,
            "status": "analyzed",
            "is_realistic": is_realistic,
            "has_fixed_ip": has_fixed_ip,
            "confidence": confidence,
            "reason": reason,
            "passed": passed,
            "model_used": model_used,
            "raw_result": parsed,
            "media_sample": media_sample,
        }

    # ------------------------------------------------------------------
    # 批量入口
    # ------------------------------------------------------------------

    async def filter_batch(self, creators: list[dict]) -> list[dict]:
        """并发分析一批创作者。"""
        tasks = [self._analyze_one(c) for c in creators]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed: list[dict] = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("Content style analysis batch item failed: %s", r)
                continue
            processed.append(r)
        return processed


# ===================================================================
# 同步包装层（Pipeline 调用）
# ===================================================================


def _get_pending_creators() -> list[dict]:
    """获取已 deep-scrape 但尚未进行内容分析的创作者。

    包含首次未分析（cca.id IS NULL）以及之前分析失败（status='failed'）的创作者，
    确保日常 pipeline 会重跑失败的案例。
    """
    return fetch_all(
        """SELECT c.id, c.username
           FROM creators c
           JOIN tweets t ON t.creator_id = c.id
           LEFT JOIN creator_content_analysis cca ON cca.creator_id = c.id
           WHERE c.bd_status IN ('rule_passed', 'ai_passed')
             AND (cca.id IS NULL OR cca.status = 'failed')
           GROUP BY c.id, c.username
           LIMIT 500"""
    )


def _write_results(results: list[dict]) -> dict:
    """将分析结果写入数据库，并更新 creators.bd_status。"""
    stats = {"analyzed": 0, "passed": 0, "rejected": 0, "skipped": 0, "failed": 0}

    for r in results:
        status = r.get("status")
        creator_id = r["creator_id"]

        if status == "skipped_no_media":
            stats["skipped"] += 1
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO creator_content_analysis
                           (creator_id, status, analyzed_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (creator_id, model_used) DO UPDATE SET
                           status = EXCLUDED.status,
                           analyzed_at = EXCLUDED.analyzed_at""",
                    (creator_id, "skipped_no_media"),
                )
            continue

        if status == "failed":
            stats["failed"] += 1
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO creator_content_analysis
                           (creator_id, status, analyzed_at, model_used)
                       VALUES (%s, %s, NOW(), %s)
                       ON CONFLICT (creator_id, model_used) DO UPDATE SET
                           status = EXCLUDED.status,
                           analyzed_at = EXCLUDED.analyzed_at,
                           model_used = EXCLUDED.model_used""",
                    (creator_id, "failed", r.get("model_used")),
                )
                cur.execute(
                    "UPDATE creators SET bd_status = 'content_rejected' WHERE id = %s",
                    (creator_id,),
                )
            continue

        # analyzed
        stats["analyzed"] += 1
        passed = r.get("passed", False)

        if passed:
            stats["passed"] += 1
            new_bd_status = None  # 保持原有 bd_status
        else:
            stats["rejected"] += 1
            new_bd_status = "content_rejected"

        raw = r.get("raw_result")
        raw_json = _Psycopg2Json(raw) if raw is not None else None

        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO creator_content_analysis
                       (creator_id, is_realistic, has_fixed_ip, confidence, model_used,
                        status, analyzed_at, raw_result, media_sample)
                   VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s)
                   ON CONFLICT (creator_id, model_used) DO UPDATE SET
                       is_realistic = EXCLUDED.is_realistic,
                       has_fixed_ip = EXCLUDED.has_fixed_ip,
                       confidence = EXCLUDED.confidence,
                       model_used = EXCLUDED.model_used,
                       status = EXCLUDED.status,
                       analyzed_at = EXCLUDED.analyzed_at,
                       raw_result = EXCLUDED.raw_result,
                       media_sample = EXCLUDED.media_sample""",
                (
                    creator_id,
                    r.get("is_realistic"),
                    r.get("has_fixed_ip"),
                    r.get("confidence"),
                    r.get("model_used"),
                    "analyzed",
                    raw_json,
                    r.get("media_sample"),
                ),
            )

            if new_bd_status:
                cur.execute(
                    "UPDATE creators SET bd_status = %s WHERE id = %s",
                    (new_bd_status, creator_id),
                )

    return stats


def filter_all_pending() -> dict:
    """同步入口：分析所有待处理的创作者。

    Returns:
        {"analyzed": int, "passed": int, "rejected": int,
         "skipped": int, "failed": int, "disabled": bool?}
    """
    if not CONTENT_STYLE_ENABLED:
        logger.info("Content style filter is disabled")
        return {"analyzed": 0, "passed": 0, "rejected": 0, "skipped": 0, "failed": 0, "disabled": True}

    creators = _get_pending_creators()
    if not creators:
        logger.info("No creators pending content style analysis")
        return {"analyzed": 0, "passed": 0, "rejected": 0, "skipped": 0, "failed": 0}

    logger.info("Starting content style analysis for %d creators", len(creators))

    filter_obj = ContentStyleFilter()

    # 分批处理，每批 batch_size 个创作者
    all_results: list[dict] = []
    batch_size = filter_obj.batch_size
    for i in range(0, len(creators), batch_size):
        batch = creators[i : i + batch_size]
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(filter_obj.filter_batch(batch))
            all_results.extend(results)
        finally:
            loop.close()

    stats = _write_results(all_results)
    logger.info("Content style filter complete: %s", stats)
    return stats
