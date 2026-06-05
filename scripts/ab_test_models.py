"""AB 测试脚本 — 用不同模型对同一批创作者做内容风格分析并对比。

用法:
    .venv/bin/python scripts/ab_test_models.py --model mimo/mimo-v2.5 --limit 10

环境变量:
    MODEL:  要测试的模型标识，如 mimo/mimo-v2.5
    LIMIT:  测试创作者数量，默认 10
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
from pathlib import Path

import httpx

# 确保项目根目录在路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import fetch_all, get_cursor
from pipeline.content_style_filter import ContentStyleFilter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


# ===================================================================
# 模型适配器注册表
# ===================================================================

class BaseModelAdapter:
    """AB 测试模型适配器基类。"""

    async def analyze(self, creator: dict, tweets: list[dict]) -> dict:
        raise NotImplementedError


class MimoAdapter(BaseModelAdapter):
    """Mimo (Anthropic 格式) 适配器。"""

    def __init__(self):
        from config.settings import MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL

        self.api_key = MIMO_API_KEY
        self.base_url = MIMO_BASE_URL
        self.model = MIMO_MODEL
        self.system_prompt = ContentStyleFilter.__dict__["SYSTEM_PROMPT"]

    async def download_image(self, url: str) -> bytes | None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                return resp.content
        except Exception as e:
            logger.warning("Failed to download image %s: %s", url, e)
            return None

    def _guess_content_type(self, url: str) -> str:
        url_lower = url.lower()
        if url_lower.endswith(".png"):
            return "image/png"
        if url_lower.endswith(".gif"):
            return "image/gif"
        if url_lower.endswith(".webp"):
            return "image/webp"
        return "image/jpeg"

    async def analyze(self, creator: dict, tweets: list[dict]) -> dict:
        creator_id = creator["id"]
        username = creator["username"]

        content_blocks = []
        intro = f"分析以下 Twitter/X 创作者（@{username}）的作品风格。"
        tweet_texts = [tw.get("text", "") for tw in tweets if tw.get("text")]
        if tweet_texts:
            intro += "\n相关推文文本：\n" + "\n---\n".join(tweet_texts[:5])
        content_blocks.append({"type": "text", "text": intro})

        media_sample = []
        media_count = 0
        for tw in tweets:
            for url in tw.get("media_urls", []) or []:
                if media_count >= 3:
                    break
                img_data = await self.download_image(url)
                if img_data:
                    content_type = self._guess_content_type(url)
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
            if media_count >= 3:
                break

        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": self.system_prompt,
            "messages": [{"role": "user", "content": content_blocks}],
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

            text_content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text_content += block.get("text", "")

        # 解析结果
        parsed = self._parse_result(text_content)
        if parsed is None:
            return {
                "creator_id": creator_id,
                "status": "failed",
                "is_realistic": None,
                "has_fixed_ip": None,
                "confidence": 0.0,
                "model_used": f"mimo/{self.model}",
            }

        is_realistic = bool(parsed.get("is_realistic"))
        has_fixed_ip = bool(parsed.get("has_fixed_ip"))
        confidence = float(parsed.get("confidence", 0))
        passed = (not is_realistic) and has_fixed_ip and confidence >= 0.7

        return {
            "creator_id": creator_id,
            "status": "analyzed",
            "is_realistic": is_realistic,
            "has_fixed_ip": has_fixed_ip,
            "confidence": confidence,
            "reason": str(parsed.get("reason", "")),
            "passed": passed,
            "model_used": f"mimo/{self.model}",
            "raw_result": parsed,
            "media_sample": media_sample,
        }

    @staticmethod
    def _parse_result(text: str) -> dict | None:
        text = text.strip()
        if not text:
            return None
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None


# 注册更多模型适配器时可扩展此处
ADAPTERS: dict[str, type[BaseModelAdapter]] = {
    "mimo": MimoAdapter,
}


# ===================================================================
# 数据库写入
# ===================================================================

def write_results(results: list[dict]) -> dict:
    stats = {"analyzed": 0, "passed": 0, "rejected": 0, "skipped": 0, "failed": 0}
    for r in results:
        status = r.get("status")
        cid = r["creator_id"]
        model = r.get("model_used")

        if status == "skipped_no_media":
            stats["skipped"] += 1
            continue
        if status == "failed":
            stats["failed"] += 1
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO creator_content_analysis (creator_id, status, analyzed_at, model_used)
                    VALUES (%s, %s, NOW(), %s)
                    ON CONFLICT (creator_id, model_used) DO UPDATE SET
                        status = EXCLUDED.status,
                        analyzed_at = EXCLUDED.analyzed_at
                """, (cid, "failed", model))
            continue

        stats["analyzed"] += 1
        if r.get("passed"):
            stats["passed"] += 1
        else:
            stats["rejected"] += 1

        raw = r.get("raw_result")
        raw_json = json.dumps(raw) if raw is not None else None
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO creator_content_analysis
                    (creator_id, is_realistic, has_fixed_ip, confidence, model_used,
                     status, analyzed_at, raw_result, media_sample)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s)
                ON CONFLICT (creator_id, model_used) DO UPDATE SET
                    is_realistic = EXCLUDED.is_realistic,
                    has_fixed_ip = EXCLUDED.has_fixed_ip,
                    confidence = EXCLUDED.confidence,
                    status = EXCLUDED.status,
                    analyzed_at = EXCLUDED.analyzed_at,
                    raw_result = EXCLUDED.raw_result,
                    media_sample = EXCLUDED.media_sample
            """, (
                cid, r.get("is_realistic"), r.get("has_fixed_ip"),
                r.get("confidence"), model, "analyzed",
                raw_json, r.get("media_sample"),
            ))
    return stats


# ===================================================================
# 主流程
# ===================================================================

async def run_ab_test(model_key: str, limit: int = 10):
    adapter_cls = ADAPTERS.get(model_key)
    if adapter_cls is None:
        raise ValueError(f"Unknown model adapter: {model_key}. Available: {list(ADAPTERS.keys())}")

    adapter = adapter_cls()

    # 获取已有主模型（Kimi）结果的创作者
    creators = fetch_all("""
        SELECT c.id, c.username
        FROM creators c
        JOIN creator_content_analysis cca ON cca.creator_id = c.id
        WHERE cca.model_used = 'moonshot/kimi-k2.5'
        ORDER BY c.id
        LIMIT %s
    """, (limit,))

    logger.info("AB test: %s vs kimi on %d creators", model_key, len(creators))

    results = []
    for creator in creators:
        tweets = fetch_all("""
            SELECT text, media_urls, media_types
            FROM tweets
            WHERE creator_id = %s AND media_urls IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 5
        """, (creator["id"],))

        logger.info("Analyzing @%s (id=%d)", creator["username"], creator["id"])
        result = await adapter.analyze(creator, tweets)
        results.append(result)

        status = "✅ PASS" if result.get("passed") else ("❌ REJECT" if result["status"] == "analyzed" else result["status"].upper())
        logger.info("  Result: %s | realistic=%s | fixed_ip=%s | conf=%s",
                    status, result.get("is_realistic"), result.get("has_fixed_ip"), result.get("confidence"))

    stats = write_results(results)
    logger.info("Write complete: %s", stats)

    # 打印对比表
    print("\n" + "=" * 100)
    print(f"AB TEST: kimi vs {model_key}")
    print("=" * 100)

    comparison = fetch_all("""
        SELECT c.username,
               cca_kimi.is_realistic as k_r, cca_kimi.has_fixed_ip as k_f, cca_kimi.confidence as k_c, cca_kimi.status as k_s,
               cca_tgt.is_realistic as t_r, cca_tgt.has_fixed_ip as t_f, cca_tgt.confidence as t_c, cca_tgt.status as t_s
        FROM creators c
        JOIN creator_content_analysis cca_kimi ON cca_kimi.creator_id = c.id AND cca_kimi.model_used = 'moonshot/kimi-k2.5'
        JOIN creator_content_analysis cca_tgt ON cca_tgt.creator_id = c.id AND cca_tgt.model_used = %s
        ORDER BY c.id
    """, (f"{model_key}/mimo-v2.5",))

    print(f"{'Username':<20} | {'Kimi':>12} | {model_key:>12} | {'Match':>5}")
    print("-" * 100)
    matches = 0
    for row in comparison:
        def v(r, f, c, s):
            if s == "failed":
                return "FAIL"
            if s == "skipped_no_media":
                return "SKIP"
            if r is None or f is None:
                return "?"
            return "PASS" if ((not r) and f and c >= 0.7) else "REJECT"

        kv = v(row["k_r"], row["k_f"], row["k_c"], row["k_s"])
        tv = v(row["t_r"], row["t_f"], row["t_c"], row["t_s"])
        match = "✅" if kv == tv else "❌"
        if kv == tv:
            matches += 1
        print(f"@{row['username']:<18} | {kv:>12} | {tv:>12} | {match:>5}")

    print("-" * 100)
    print(f"Match rate: {matches}/{len(comparison)} ({matches / len(comparison) * 100:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="AB test content style filter with different models")
    parser.add_argument("--model", default="mimo", help="Model adapter key to test (default: mimo)")
    parser.add_argument("--limit", type=int, default=10, help="Number of creators to test (default: 10)")
    args = parser.parse_args()

    asyncio.run(run_ab_test(args.model, args.limit))


if __name__ == "__main__":
    main()
