# CraftifyX Miner 7.0

> AI 驱动的海外创作者自动发现与评估系统（**7.0 在 6.0 架构上迭代**，见文档）

**主文档**：[docs/CraftifyX-Miner-7.0-项目说明书.md](docs/CraftifyX-Miner-7.0-项目说明书.md) · [docs/CraftifyX-Miner-7.0-开发实现方案.md](docs/CraftifyX-Miner-7.0-开发实现方案.md)

CraftifyX Miner 是一套低成本（≤$500/月）、4 周可交付 MVP 的自动化系统，帮助 BD 团队**每天产出约 300-500 名带 SPS 的海外创作者候选人**（VTuber / OC / 游戏开发者等），取代人工地毯式搜索。

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
  → Streamlit BD Dashboard (4 页面)
  → BD 判定 (Interested / Rejected / Deferred)
  → Sales Feedback → Seed 自动晋升 (飞轮进化)
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
│   ├── connection.py           # 连接池管理
│   ├── schema.sql              # 9 张核心表 DDL
│   ├── indexes.sql             # 查询优化索引
│   └── migrations/             # 增量迁移脚本
├── server/                     # Flask 后端
│   ├── app.py                  # 主应用入口
│   ├── webhook.py              # Apify Webhook 接收 + 三级管道流转
│   └── api.py                  # 内部 REST API (stats / cost / trigger)
├── pipeline/                   # 数据管道
│   ├── seed_import.py          # Phase 1: 种子导入 (CSV → Tier → DB)
│   ├── discovery.py            # 每日发现引擎 (含 20% 随机探索)
│   ├── bio_rule_filter.py      # Level 1/2 规则快筛 (BioRuleFilter)
│   ├── ai_filter.py            # Level 3 LLM 批量过滤 (AIFilter + LLMClient)
│   ├── deep_scrape.py          # 深度抓取触发 (Residential Proxy)
│   ├── feature_engine.py       # 10 维指标计算
│   ├── sps_scorer.py           # SPS 评分 + 中心度分层
│   └── evolution.py            # 飞轮进化 (Seed 晋升 + 月度报告)
├── dashboard/                  # Streamlit BD 工作台
│   ├── app.py                  # 主入口
│   ├── pages/
│   │   ├── 1_daily_report.py   # 每日发现报告
│   │   ├── 2_candidates.py     # 候选人浏览与 BD 判定
│   │   ├── 3_outreach.py       # 联系追踪与销售反馈
│   │   └── 4_cost_monitor.py   # 成本监控面板
│   └── components/
│       └── radar_chart.py      # 10 维雷达图 (Plotly)
├── cron/                       # 定时任务
│   └── daily_job.py            # APScheduler 编排
├── tests/                      # 测试
│   ├── test_bio_rule_filter.py # BIO 规则快筛测试
│   ├── test_ai_filter.py       # AI 过滤测试
│   ├── test_feature_engine.py  # 指标计算测试
│   └── test_sps_scorer.py      # SPS 评分测试
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
docker compose up -d
```

这将启动 4 个服务：
- **db** — PostgreSQL 15 (自动执行 schema.sql + indexes.sql)
- **server** — Flask 后端 (Gunicorn, :5000)
- **dashboard** — Streamlit Dashboard (:8501)
- **cron** — APScheduler 定时任务

### 5. 手动启动（开发模式）

```bash
# 创建数据库
psql -U miner -d craftifyx_miner -f db/schema.sql
psql -U miner -d craftifyx_miner -f db/indexes.sql

# 启动 Flask 后端
python -m server.app

# 启动 Streamlit Dashboard
streamlit run dashboard/app.py

# 启动定时任务
python cron/daily_job.py
```

### 6. 导入种子数据

```bash
python -m pipeline.seed_import --csv path/to/merged_creators.csv
```

### 7. 运行测试

```bash
pytest tests/ -v
```

## 定时任务 Schedule

| 时间 | 任务 | 说明 |
|------|------|------|
| 08:00 | `generate_daily_seeds` | 生成当日锚点 (80% S/A Seed + 20% 探索) |
| 08:10 | `trigger_l1_scan` | 触发 Apify Following 扫描 |
| 12:00 | `deep_scrape_and_score` | 深度抓取 + 10 维指标 + SPS 评分 |
| 23:00 | `daily_summary` | 日报统计 + 成本更新 + Seed 晋升检查 |

Webhook 回调后自动执行: 规则快筛 → AI 过滤 → 状态更新。

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
| Dashboard | Streamlit + Plotly |
| 定时任务 | APScheduler |
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

- [项目说明书 (7.0)](docs/CraftifyX-Miner-7.0-项目说明书.md) — 面向决策层的整体介绍
- [开发实现方案 (7.0)](docs/CraftifyX-Miner-7.0-开发实现方案.md) — 完整开发任务清单与代码设计
- [项目说明书 (6.0)](docs/CraftifyX-Miner-6.0-项目说明书.md) — 6.0 版本参考
- [开发实现方案 (6.0)](docs/CraftifyX-Miner-6.0-开发实现方案.md) — 6.0 版本实现参考

## License

Private — 仅限内部使用。
