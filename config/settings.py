"""全局配置 — 从环境变量加载，敏感值不写入代码。"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- 数据库 ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://miner:password@localhost:5432/craftifyx_miner")

# --- Apify ---
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
APIFY_WEBHOOK_SECRET = os.getenv("APIFY_WEBHOOK_SECRET", "")

# --- LLM (统一 OpenAI 兼容接口) ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "dashscope")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-plus")
LLM_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "50"))

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

FALLBACK_CHAIN = ["dashscope", "moonshot", "deepseek", "zhipu", "minimax"]

# --- Flask ---
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-in-production")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

# --- Streamlit ---
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))

# --- 成本控制 ---
DAILY_APIFY_BUDGET_USD = float(os.getenv("DAILY_APIFY_BUDGET_USD", "20"))
MONTHLY_LLM_BUDGET_USD = float(os.getenv("MONTHLY_LLM_BUDGET_USD", "10"))

# --- 发现引擎 ---
EXPLORATION_RATIO = float(os.getenv("EXPLORATION_RATIO", "0.20"))
DAILY_ANCHOR_COUNT = int(os.getenv("DAILY_ANCHOR_COUNT", "20"))
MAX_FOLLOWING_PER_ANCHOR = int(os.getenv("MAX_FOLLOWING_PER_ANCHOR", "500"))
