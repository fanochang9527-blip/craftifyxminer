"""Apify Webhook 接收路由 — 接收 Actor 完成回调，触发数据处理管道。"""

import hmac
import hashlib
import logging
import threading

from flask import Blueprint, request, jsonify
from apify_client import ApifyClient

from config.settings import APIFY_WEBHOOK_SECRET, APIFY_API_TOKEN
from db.connection import get_cursor

logger = logging.getLogger(__name__)

webhook_bp = Blueprint("webhook", __name__)


def _verify_signature(payload: bytes, signature: str) -> bool:
    if not APIFY_WEBHOOK_SECRET:
        return True
    expected = hmac.new(
        APIFY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _fetch_and_store_dataset(dataset_id: str) -> dict:
    """Pull items from an Apify dataset and upsert into creators table.

    Returns summary stats: {total, inserted, updated}.
    """
    client = ApifyClient(APIFY_API_TOKEN)
    items = list(client.dataset(dataset_id).iterate_items())
    logger.info("Fetched %d items from dataset %s", len(items), dataset_id)

    inserted = updated = 0
    for item in items:
        username = item.get("username") or item.get("screen_name") or item.get("userName")
        if not username:
            continue
        username = username.lstrip("@").lower()

        bio = item.get("description") or item.get("bio") or ""
        website = item.get("website") or item.get("url") or ""
        followers = item.get("followers") or item.get("followersCount") or 0
        following = item.get("following") or item.get("friendsCount") or 0
        tweets_count = item.get("statusesCount") or item.get("tweetsCount") or 0

        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO creators (username, bio, website, followers, following, tweets_count)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (username) DO UPDATE SET
                       bio = COALESCE(NULLIF(EXCLUDED.bio, ''), creators.bio),
                       website = COALESCE(NULLIF(EXCLUDED.website, ''), creators.website),
                       followers = EXCLUDED.followers,
                       following = EXCLUDED.following,
                       tweets_count = EXCLUDED.tweets_count
                   RETURNING (xmax = 0) AS is_insert""",
                (username, bio, website, followers, following, tweets_count),
            )
            row = cur.fetchone()
            if row and row["is_insert"]:
                inserted += 1
            else:
                updated += 1

    return {"total": len(items), "inserted": inserted, "updated": updated}


def _process_webhook_async(dataset_id: str) -> None:
    """Background worker: fetch dataset -> rule filter -> AI filter."""
    try:
        stats = _fetch_and_store_dataset(dataset_id)
        logger.info("Dataset %s stored: %s", dataset_id, stats)

        from pipeline.bio_rule_filter import BioRuleFilter
        from pipeline.ai_filter import AIFilter

        rule_filter = BioRuleFilter()
        ai_filter = AIFilter()

        with get_cursor() as cur:
            cur.execute(
                "SELECT id, bio, website FROM creators WHERE bd_status = 'pending' AND bio IS NOT NULL"
            )
            candidates = cur.fetchall()

        grey_zone = []
        for c in candidates:
            result = rule_filter.filter(c["bio"], c.get("website") or "")
            if result["passed"] is True:
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_status = 'rule_passed' WHERE id = %s",
                        (c["id"],),
                    )
            elif result["passed"] is False:
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_status = 'rule_rejected' WHERE id = %s",
                        (c["id"],),
                    )
            else:
                grey_zone.append(c)

        if grey_zone:
            import asyncio

            bio_batch = [{"id": c["id"], "bio": c["bio"]} for c in grey_zone]
            loop = asyncio.new_event_loop()
            try:
                ai_results = loop.run_until_complete(ai_filter.filter_batch(bio_batch))
            finally:
                loop.close()

            for r in ai_results:
                status = "ai_passed" if r.get("result") == "YES" else "ai_rejected"
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE creators SET bd_status = %s WHERE id = %s",
                        (status, r["bio_id"]),
                    )

        logger.info("Pipeline complete for dataset %s", dataset_id)
    except Exception:
        logger.exception("Error processing dataset %s", dataset_id)


@webhook_bp.route("/apify-webhook", methods=["POST"])
def receive_apify_data():
    signature = request.headers.get("X-Apify-Webhook-Secret", "")
    if not _verify_signature(request.data, signature):
        return jsonify({"error": "invalid signature"}), 403

    data = request.json
    dataset_id = data.get("resource", {}).get("defaultDatasetId")
    if not dataset_id:
        dataset_id = data.get("datasetId")
    if not dataset_id:
        return jsonify({"error": "missing datasetId"}), 400

    thread = threading.Thread(target=_process_webhook_async, args=(dataset_id,), daemon=True)
    thread.start()

    return jsonify({"status": "accepted", "datasetId": dataset_id}), 202
