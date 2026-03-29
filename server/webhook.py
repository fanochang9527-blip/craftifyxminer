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
        logger.error("APIFY_WEBHOOK_SECRET is not set — rejecting webhook")
        return False
    expected = hmac.new(
        APIFY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _process_webhook_async(dataset_id: str) -> None:
    """Background worker: fetch dataset -> rule filter -> AI filter."""
    try:
        from pipeline.intake import process_dataset
        client = ApifyClient(APIFY_API_TOKEN)
        result = process_dataset(client, dataset_id)
        logger.info("Pipeline complete for dataset %s: %s", dataset_id, result)
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
