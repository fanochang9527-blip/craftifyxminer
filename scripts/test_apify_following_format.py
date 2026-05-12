"""快速测试：确认 Apify twitter-user-scraper 在 getFollowing 模式下返回的数据结构。

重点观察每个 following item 是否自带来源信息（如 followed_by / sourceHandle 等字段）。
"""

import json
import logging
import sys

import yaml
from apify_client import ApifyClient

sys.path.insert(0, "/app")
from db.connection import fetch_all  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

APIFY_CONFIG_PATH = "/app/config/apify_config.yaml"


def load_token() -> str:
    import os
    token = os.environ.get("APIFY_API_TOKEN")
    if token:
        return token
    raise RuntimeError("APIFY_API_TOKEN not found in environment")


def main() -> None:
    seeds = fetch_all(
        "SELECT id, username, platform_account_id FROM creators WHERE is_seed = true ORDER BY id LIMIT 5"
    )
    if not seeds:
        logger.error("No seeds found in DB")
        sys.exit(1)

    print("Available seeds:")
    for s in seeds:
        print(f"  id={s['id']:<3} username='{s['username']}'")

    # 用 platform_account_id 作为实际 Twitter handle
    target = next((s for s in seeds if s["platform_account_id"] and " " not in s["platform_account_id"]), seeds[0])
    handle = target["platform_account_id"].strip().lstrip("@")
    seed_id = target["id"]

    print(f"\n=> 测试种子: id={seed_id}, handle='{handle}'")
    print(f"=> 爬取其 following 列表前 10 条...\n")

    token = load_token()
    client = ApifyClient(token)

    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    following_cfg = cfg["following_actor"]
    actor_id = following_cfg["actor_id"]
    base_input = following_cfg["input"].copy()
    base_input["twitterHandles"] = [handle]
    base_input["maxItems"] = 10
    base_input["getFollowing"] = True
    base_input["getFollowers"] = False

    print(f"Actor: {actor_id}")
    print(f"Input: {json.dumps(base_input, indent=2, ensure_ascii=False)}\n")

    run = client.actor(actor_id).call(run_input=base_input)
    run_id = run.get("id", "")
    print(f"Run completed: {run_id}")

    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        print("No dataset returned.")
        return

    items = list(client.dataset(dataset_id).iterate_items())
    print(f"Total items returned: {len(items)}\n")

    # 打印每个 item 的完整字段和值（截断长文本）
    for idx, item in enumerate(items, 1):
        print(f"--- Item {idx} ---")
        for k, v in sorted(item.items()):
            val = v
            if isinstance(v, str) and len(v) > 120:
                val = v[:120] + "..."
            elif isinstance(v, list) and len(v) > 3:
                val = v[:3] + [f"... ({len(v)} total)"]
            print(f"  {k}: {val}")
        print()

    # 汇总所有出现过的字段名
    all_keys = set()
    for item in items:
        all_keys.update(item.keys())
    print(f"=== 所有出现过的字段 ({len(all_keys)} 个) ===")
    print(", ".join(sorted(all_keys)))

    # 特别关注是否有来源相关字段
    source_like = [k for k in all_keys if any(w in k.lower() for w in ["source", "followed_by", "anchor", "origin", "from", "parent"])]
    if source_like:
        print(f"\n>>> 发现可能的来源字段: {source_like}")
    else:
        print("\n>>> 未发现明显的来源/来源字段（如 followed_by / sourceHandle 等）")
        print(">>> 结论：需要改为逐个种子扫描，才能在代码层知道每条 following 数据来自哪个种子。")


if __name__ == "__main__":
    main()
