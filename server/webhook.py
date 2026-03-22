"""Apify Webhook 接收路由 — 接收 Actor 完成回调，触发数据处理管道。"""

import hmac
import hashlib

from flask import Blueprint, request, jsonify

from config.settings import APIFY_WEBHOOK_SECRET

webhook_bp = Blueprint("webhook", __name__)


def _verify_signature(payload: bytes, signature: str) -> bool:
    if not APIFY_WEBHOOK_SECRET:
        return True
    expected = hmac.new(
        APIFY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@webhook_bp.route("/apify-webhook", methods=["POST"])
def receive_apify_data():
    signature = request.headers.get("X-Apify-Webhook-Secret", "")
    if not _verify_signature(request.data, signature):
        return jsonify({"error": "invalid signature"}), 403

    data = request.json
    dataset_id = data.get("resource", {}).get("defaultDatasetId")
    if not dataset_id:
        return jsonify({"error": "missing datasetId"}), 400

    # TODO: 从 Apify dataset 拉取数据 -> 规则快筛 -> AI 过滤 -> 入库
    # pipeline.process_webhook_data(dataset_id)

    return jsonify({"status": "received", "datasetId": dataset_id}), 200
