# CraftifyX Miner 6.0

> AI 驱动的海外创作者自动发现与评估系统

CraftifyX Miner 是一套低成本（≤$500/月）、4 周可交付的自动化系统，帮助 BD 团队**每天自动发现 300-500 名海外创作者**（VTuber / OC / 游戏开发者等），取代人工地毯式搜索。

## 系统架构

```
三级智能管道:

L1 浅层扫描 (Datacenter Proxy)
  → Seed 库 (80% 高价值 + 20% 随机探索)
  → Apify Following 扫描 (~5000 人/日)

L2 AI 预过滤 (国产大模型)
  → Level 1/2 规则快筛 (Link DNA + 语义矩阵 + Emoji 信号)
  → Level 3 LLM 语义兜底 (Qwen/Kimi/DeepSeek, 仅处理 ~30% 灰区)
  → 产出 500-800 候选人/日

L3 深度抓取 (Residential Proxy)
  → Profile + 10 Tweets
  → 10 维指标计算 → SPS 评分 + 中心度分层
  → 产出 300-500 带评分的候选人/日

应用层
  → Streamlit BD Dashboard
  → BD 判定 (Interested / Rejected / Deferred)
  → Sales Feedback → Seed 自动晋升
```

## 项目结构

```
craftifyxminer/
├── config/                     # 配置文件
│   ├── settings.py             # 环境变量与全局配置
│   ├── apify_config.yaml       # Apify Actor 参数
│   ├── weights.yaml            # 5 类创作者 SPS 权重矩阵
│   └── bio_rules.yaml          # BIO 知识库 (Link DNA / 语义矩阵 / Emoji 信号)
├── db/                         # 数据库
│   ├── schema.sql              # 9 张核心表 DDL
│   ├── indexes.sql             # 查询优化索引
│   └── seed_import.sql         # 种子导入脚本
├── server/                     # Flask 后端
│   ├── app.py                  # 主应用入口
│   ├── webhook.py              # Apify Webhook 接收
│   └── api.py                  # 内部 REST API
├── pipeline/                   # 数据管道
│   ├── seed_import.py          # Phase 1: 种子导入
│   ├── discovery.py            # 每日发现引擎 (含随机探索)
│   ├── bio_rule_filter.py      # Level 1/2 规则快筛
│   ├── ai_filter.py            # Level 3 国产大模型过滤
│   ├── deep_scrape.py          # 深度抓取触发
│   ├── feature_engine.py       # 10 维指标计算
│   ├── sps_scorer.py           # SPS 评分 + 中心度
│   └── evolution.py            # 飞轮进化 (Seed 晋升)
├── dashboard/                  # Streamlit BD 工作台
│   ├── app.py                  # 主入口
│   ├── pages/                  # 4 个功能页面
│   └── components/             # 可复用组件 (雷达图等)
├── cron/                       # 定时任务
│   └── daily_job.py            # APScheduler 编排
├── tests/                      # 测试
├── docs/                       # 项目文档
├── .env.example                # 环境变量模板
├── requirements.txt            # Python 依赖
├── Dockerfile
└── docker-compose.yml          # 一键启动
```

## 快速开始

### 前提条件

- Python 3.11+
- PostgreSQL 15+（或使用 Docker）
- Apify 账号（Starter 计划）
- 国产大模型 API Key（阿里云百炼 / DeepSeek / Kimi 等任一）

### 1. 克隆仓库

```bash
git clone https://github.com/YOUR_USERNAME/craftifyxminer.git
cd craftifyxminer
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入真实的 API Key、数据库密码等
```

> **重要**: `.env` 文件包含敏感信息，已在 `.gitignore` 中排除，切勿提交到 Git。

### 3. 安装依赖

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. 启动服务（Docker 方式）

```bash
docker-compose up -d
```

或手动启动各服务：

```bash
# 创建数据库
psql -U miner -d craftifyx_miner -f db/schema.sql

# 启动 Flask 后端
python -m server.app

# 启动 Streamlit Dashboard
streamlit run dashboard/app.py

# 启动定时任务
python cron/daily_job.py
```

### 5. 导入种子数据

```bash
python -m pipeline.seed_import --csv path/to/merged_creators.csv
```

## 安全须知

本项目严格保护敏感信息：

| 文件类型 | 处理方式 |
|---------|---------|
| `.env` (API Key, 数据库密码) | `.gitignore` 排除，仅提供 `.env.example` 模板 |
| `*.csv` (创作者数据) | `.gitignore` 排除，不入库 |
| `*.docx / *.pdf` (业务文档) | `.gitignore` 排除，不入库 |
| `*.pkl` (模型文件) | `.gitignore` 排除，不入库 |
| `models/*.json` (动态权重) | `.gitignore` 排除，仅保留 `.gitkeep` |

如需共享种子数据或模型文件，请通过安全渠道（加密传输 / 内部网盘）传递，**不要**提交到 Git。

## 技术栈

| 组件 | 技术选型 |
|------|---------|
| 后端 | Python (Flask / aiohttp) |
| 数据采集 | Apify (Twitter/X Actor) |
| AI 过滤 | 国产大模型 (Qwen / Kimi / DeepSeek，OpenAI 兼容接口) |
| 数据库 | PostgreSQL 15+ |
| Dashboard | Streamlit |
| 部署 | Docker Compose + Nginx |

## 月度成本

| 费用项 | 预算 |
|--------|------|
| Apify 订阅 + 代理 | ~$380 |
| 国产大模型 API | ~$2-20 |
| 云服务器 (阿里云 2C4G) | ~$3-15 |
| 数据库 | ~$0-8 |
| 缓冲 | ~$90-110 |
| **合计** | **≤$500/月** |

## 文档

详细的产品设计、技术方案、实施计划请参阅 `docs/` 目录：

- [项目说明书](docs/CraftifyX-Miner-6.0-项目说明书.md) — 面向决策层的整体介绍
- [开发实现方案](docs/CraftifyX-Miner-6.0-开发实现方案.md) — 完整开发任务清单与代码设计
- [爬虫方案选型](docs/爬虫方案.md) — Apify vs Scrapling 对比分析
- [系统完整设计](docs/CraftifyX-Miner-6.0.md) — 四层架构、业务流程、数据模型全文

## License

Private — 仅限内部使用。
