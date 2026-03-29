"""全局配置 — 从环境变量加载，敏感值不写入代码。"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- 数据库（默认库名/用户与 .env 中 POSTGRES_DB / POSTGRES_USER 一致）---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://miner:password@localhost:5432/craftifyx_miner")

# --- Apify ---
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
APIFY_WEBHOOK_SECRET = os.getenv("APIFY_WEBHOOK_SECRET", "")

# --- LLM (统一 OpenAI 兼容接口) ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "dashscope")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-plus")
LLM_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "50"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))

PROVIDER_CONFIGS = {
    "dashscope": {
        "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
        "base_url": os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    },
    "moonshot": {
        "api_key": os.getenv("MOONSHOT_API_KEY", ""),
        "base_url": os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
    },
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    },
    "zhipu": {
        "api_key": os.getenv("ZHIPU_API_KEY", ""),
        "base_url": os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
    },
    "minimax": {
        "api_key": os.getenv("MINIMAX_API_KEY", ""),
        "base_url": os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
    },
}

FALLBACK_CHAIN = ["moonshot", "dashscope", "deepseek", "zhipu", "minimax"]

# --- LLM provider-specific model overrides ---
PROVIDER_MODELS = {
    "moonshot": os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
    "dashscope": os.getenv("DASHSCOPE_MODEL", "qwen3.5-plus"),
    "deepseek": os.getenv("DEEPSEEK_MODEL", "deepseek-v3.2"),
    "zhipu": os.getenv("ZHIPU_MODEL", "glm-4-flash"),
    "minimax": os.getenv("MINIMAX_MODEL", "MiniMax-Text-01"),
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
DAILY_APIFY_BUDGET_USD = float(os.getenv("DAILY_APIFY_BUDGET_USD", "20"))
MONTHLY_LLM_BUDGET_USD = float(os.getenv("MONTHLY_LLM_BUDGET_USD", "10"))

# --- 发现引擎 ---
EXPLORATION_RATIO = float(os.getenv("EXPLORATION_RATIO", "0.20"))
DAILY_ANCHOR_COUNT = int(os.getenv("DAILY_ANCHOR_COUNT", "20"))
MAX_FOLLOWING_PER_ANCHOR = int(os.getenv("MAX_FOLLOWING_PER_ANCHOR", "500"))

# --- 深度抓取（每批人数，冒烟时可设 3–5）---
DEEP_SCRAPE_BATCH_SIZE = int(os.getenv("DEEP_SCRAPE_BATCH_SIZE", "50"))

# --- 路径 ---
BIO_RULES_PATH = PROJECT_ROOT / "config" / "bio_rules.yaml"
WEIGHTS_PATH = PROJECT_ROOT / "config" / "weights.yaml"
APIFY_CONFIG_PATH = PROJECT_ROOT / "config" / "apify_config.yaml"
