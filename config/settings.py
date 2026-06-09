"""全局配置 — 从环境变量加载，敏感值不写入代码。"""

import os
from pathlib import Path
from dotenv import load_dotenv

# override=False：已存在的环境变量（含 compose 注入的 DATABASE_URL=...@db）不得被磁盘上的 .env 覆盖
load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- 数据库（默认库名/用户与 .env 中 POSTGRES_DB / POSTGRES_USER 一致）---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://miner:password@localhost:5432/craftifyx_miner")

# --- Apify ---
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
APIFY_WEBHOOK_SECRET = os.getenv("APIFY_WEBHOOK_SECRET", "")

# --- Apify Actor 切换（实验性费用优化）---
# "apidojo" = 默认官方 Actor（稳定，费用较高）
# "alt"     = 备选 Actor（apify_config.yaml 中 alt_*_actor 配置，费用较低）
APIFY_L1_ACTOR = os.getenv("APIFY_L1_ACTOR", "apidojo")
APIFY_L2_ACTOR = os.getenv("APIFY_L2_ACTOR", "apidojo")

# --- LLM (统一 OpenAI 兼容接口) ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "moonshot")
LLM_MODEL = os.getenv("LLM_MODEL", "kimi-k2.5")
LLM_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "5"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
# 全局默认；各厂商实际上限见 PROVIDER_MAX_OUTPUT_TOKENS（DeepSeek 等为 8192）
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))

# 各 OpenAI 兼容厂商的 completion 上限不同；ai_filter 会取 min(LLM_MAX_TOKENS, cap)
PROVIDER_MAX_OUTPUT_TOKENS = {
    "moonshot": 16384,
    "deepseek": 8192,
    "dashscope": 8192,
}

PROVIDER_CONFIGS = {
    "moonshot": {
        "api_key": os.getenv("MOONSHOT_API_KEY", ""),
        "base_url": os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
    },
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    },
    "dashscope": {
        "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
        "base_url": os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    },
}

# 默认仅 Kimi（Moonshot）；需 DeepSeek/百炼时再设 LLM_FALLBACK_CHAIN=moonshot,deepseek,dashscope
_fallback_raw = os.getenv("LLM_FALLBACK_CHAIN", "moonshot")
FALLBACK_CHAIN = [p.strip() for p in _fallback_raw.split(",") if p.strip()]

# --- LLM provider-specific model overrides ---
PROVIDER_MODELS = {
    "moonshot": os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
    "deepseek": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    "dashscope": os.getenv("DASHSCOPE_MODEL", "qwen3.5-plus"),
}

# --- Flask ---
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-in-production")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

# --- JWT ---
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", FLASK_SECRET_KEY)
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

# --- Streamlit ---
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))

# --- 成本控制 ---
MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "500"))
DAILY_APIFY_BUDGET_USD = float(os.getenv("DAILY_APIFY_BUDGET_USD", "40"))
MONTHLY_LLM_BUDGET_USD = float(os.getenv("MONTHLY_LLM_BUDGET_USD", "10"))
APIFY_BUDGET_HARD_LIMIT = os.getenv("APIFY_BUDGET_HARD_LIMIT", "false").lower() in ("1", "true", "yes")

# --- 发现引擎 ---
DAILY_ANCHOR_COUNT = int(os.getenv("DAILY_ANCHOR_COUNT", "20"))
MAX_FOLLOWING_PER_ANCHOR = int(os.getenv("MAX_FOLLOWING_PER_ANCHOR", "500"))
ANCHOR_HIGH_VALUE_COOLDOWN_DAYS = int(os.getenv("ANCHOR_HIGH_VALUE_COOLDOWN_DAYS", "3"))
ANCHOR_NORMAL_COOLDOWN_DAYS = int(os.getenv("ANCHOR_NORMAL_COOLDOWN_DAYS", "7"))
ANCHOR_LOW_VALUE_COOLDOWN_DAYS = int(os.getenv("ANCHOR_LOW_VALUE_COOLDOWN_DAYS", "14"))

# --- 深度抓取（每批人数，冒烟时可设 3–5）---
DEEP_SCRAPE_BATCH_SIZE = int(os.getenv("DEEP_SCRAPE_BATCH_SIZE", "300"))

# --- 路径 ---
BIO_RULES_PATH = PROJECT_ROOT / "config" / "bio_rules.yaml"
WEIGHTS_PATH = PROJECT_ROOT / "config" / "weights.yaml"
APIFY_CONFIG_PATH = PROJECT_ROOT / "config" / "apify_config.yaml"
MODEL_PATH = PROJECT_ROOT / "models" / "sps_model.joblib"
MODEL_META_PATH = PROJECT_ROOT / "models" / "sps_model_meta.json"
SELLABILITY_MODEL_PATH = PROJECT_ROOT / "models" / "sellability_model.joblib"
SELLABILITY_MODEL_META_PATH = PROJECT_ROOT / "models" / "sellability_model_meta.json"
# V2 实验组模型（使用原始拆分特征）
SPS_MODEL_V2_PATH = PROJECT_ROOT / "models" / "sps_model_v2.joblib"
SPS_MODEL_V2_META_PATH = PROJECT_ROOT / "models" / "sps_model_v2_meta.json"
SELLABILITY_MODEL_V2_PATH = PROJECT_ROOT / "models" / "sellability_model_v2.joblib"
SELLABILITY_MODEL_V2_META_PATH = PROJECT_ROOT / "models" / "sellability_model_v2_meta.json"

# --- 双模型口径 ---
# 资格模型阈值：>= 阈值判定为“建议联系”
SELLABILITY_SCORE_THRESHOLD = float(os.getenv("SELLABILITY_SCORE_THRESHOLD", "60"))
# 初始样本打标阈值：total_sales > 阈值为正样本，< 阈值为负样本（=阈值不参与）
SELLABILITY_LABEL_SALES_THRESHOLD = float(os.getenv("SELLABILITY_LABEL_SALES_THRESHOLD", "50"))
# SPS 作为“预测销量评分”：按 predicted_sales / normalizer 映射到 0-100
SPS_SALES_NORMALIZER = float(os.getenv("SPS_SALES_NORMALIZER", "100"))
# 工作台灰度阶段：1=只展示新字段不改默认排序；2=默认按双模型排序
BD_WORKBENCH_PHASE = int(os.getenv("BD_WORKBENCH_PHASE", "1"))
# 非 sellable 候选在双模型排序中的 SPS 降权系数（0-1）
NON_SELLABLE_SPS_WEIGHT = float(os.getenv("NON_SELLABLE_SPS_WEIGHT", "0.35"))

# --- 创作者类型 ---
# oc_creator      = 原创 OC / 原创插画 / 动漫创作者  (XLS: B-原创OC)
# vtuber          = VTuber / 虚拟 IP / 虚拟主播       (XLS: C-虚拟IP)
# fan_artist      = 同人 / 二次创作                    (XLS: E-二创IP)
# game_creator    = 游戏 / 官方 IP                     (XLS: A-官方IP)
# content_creator = YouTube/TikTok 网红（非绘画类）    (当前种子数据无此类型)
# unknown         = 无法判断
CREATOR_TYPES = ("oc_creator", "vtuber", "fan_artist", "game_creator", "content_creator", "unknown")

# --- Growth Score ---
GROWTH_SPAN_MIN_DAYS = int(os.getenv("GROWTH_SPAN_MIN_DAYS", "30"))
GROWTH_ANOMALY_DROP_THRESHOLD = float(os.getenv("GROWTH_ANOMALY_DROP_THRESHOLD", "-0.80"))
GROWTH_ANOMALY_MIN_FOLLOWERS = int(os.getenv("GROWTH_ANOMALY_MIN_FOLLOWERS", "1000"))
FOLLOWER_REFRESH_INTERVAL_DAYS = int(os.getenv("FOLLOWER_REFRESH_INTERVAL_DAYS", "3"))
FOLLOWER_REFRESH_BATCH_SIZE = int(os.getenv("FOLLOWER_REFRESH_BATCH_SIZE", "100"))

# --- 备选: Mimo (Anthropic 原生格式) ---
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/anthropic")
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5")

# --- 多模态内容风格过滤 (支持 AB 测试切换模型) ---
CONTENT_STYLE_ENABLED = os.getenv("CONTENT_STYLE_ENABLED", "true").lower() in ("1", "true", "yes")
CONTENT_STYLE_LLM_PROVIDER = os.getenv("CONTENT_STYLE_LLM_PROVIDER", LLM_PROVIDER)
CONTENT_STYLE_LLM_MODEL = os.getenv("CONTENT_STYLE_LLM_MODEL", LLM_MODEL)
CONTENT_STYLE_MAX_MEDIA_PER_CREATOR = int(os.getenv("CONTENT_STYLE_MAX_MEDIA_PER_CREATOR", "5"))
CONTENT_STYLE_MAX_TWEETS_PER_CREATOR = int(os.getenv("CONTENT_STYLE_MAX_TWEETS_PER_CREATOR", "10"))
CONTENT_STYLE_CONFIDENCE_THRESHOLD = float(os.getenv("CONTENT_STYLE_CONFIDENCE_THRESHOLD", "0.7"))
CONTENT_STYLE_BATCH_SIZE = int(os.getenv("CONTENT_STYLE_BATCH_SIZE", "5"))
# 内容风格过滤可独立配置 fallback chain；未配置则复用全局 FALLBACK_CHAIN
_content_style_fallback_raw = os.getenv("CONTENT_STYLE_FALLBACK_CHAIN", "").strip()
CONTENT_STYLE_FALLBACK_CHAIN = (
    [p.strip() for p in _content_style_fallback_raw.split(",") if p.strip()]
    if _content_style_fallback_raw
    else list(FALLBACK_CHAIN)
)

# --- 粉丝量急剧下降预警 ---
FOLLOWER_DROP_ALERT_THRESHOLD = float(os.getenv("FOLLOWER_DROP_ALERT_THRESHOLD", "-0.20"))
FOLLOWER_DROP_MIN_FOLLOWERS = int(os.getenv("FOLLOWER_DROP_MIN_FOLLOWERS", "20000"))

# --- 种子粉丝量大幅增长提醒 ---
SEED_GROWTH_ALERT_THRESHOLD = float(os.getenv("SEED_GROWTH_ALERT_THRESHOLD", "0.20"))
SEED_GROWTH_MIN_FOLLOWERS = int(os.getenv("SEED_GROWTH_MIN_FOLLOWERS", "20000"))
