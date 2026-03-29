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
├── auth/                       # 认证与权限
│   ├── password.py             # bcrypt 哈希 / 复杂度校验
│   ├── login.py                # 登录核心逻辑 (锁定 / 审计)
│   ├── session.py              # Streamlit session 管理
│   ├── decorators.py           # Flask @login_required / @admin_required (JWT)
│   └── manage.py               # CLI 用户管理 (create-admin / reset-password)
├── db/                         # 数据库
│   ├── connection.py           # 连接池管理
│   ├── schema.sql              # 11 张核心表 DDL
│   ├── indexes.sql             # 查询优化索引
│   └── migrations/             # 增量迁移脚本
├── server/                     # Flask 后端
│   ├── app.py                  # 主应用入口 (含 JWT 登录 + 限流)
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
│   ├── app.py                  # 主入口 (含登录门 + 语言切换)
│   ├── i18n.py                 # 国际化翻译加载器
│   ├── locales/
│   │   ├── zh.yaml             # 中文翻译
│   │   └── en.yaml             # 英文翻译
│   ├── pages/
│   │   ├── 1_daily_report.py   # 每日发现报告
│   │   ├── 2_candidates.py     # 候选人浏览与 BD 判定
│   │   ├── 3_outreach.py       # 联系追踪与销售反馈
│   │   ├── 4_cost_monitor.py   # 成本监控面板
│   │   └── 5_admin.py          # Admin 管理面板 (用户/审计)
│   └── components/
│       └── radar_chart.py      # 10 维雷达图 (Plotly)
├── nginx/                      # Nginx 反向代理配置
│   └── nginx.conf              # 含安全头 + 限流规则
├── scripts/                    # 运维脚本
│   ├── deploy.sh               # 一键部署 (Docker 安装 + .env 配置 + 启动)
│   └── backup_db.sh            # PostgreSQL 备份 (pg_dump + 7 天保留)
├── cron/                       # 定时任务
│   └── daily_job.py            # APScheduler 编排
├── tests/                      # 测试
├── docs/                       # 项目文档
├── .env.example                # 环境变量模板
├── requirements.txt            # Python 依赖
├── Dockerfile                  # 非 root 用户镜像
├── docker-compose.yml          # 本地开发 (含 PG 容器)
└── docker-compose.prod.yml     # 生产部署 (Nginx + 无 PG 容器)
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

**数据库命名（默认勿改）**：逻辑库名 `craftifyx_miner`、连接用户 `miner`，与 `DATABASE_URL` 及 `.env` 中 `POSTGRES_DB` / `POSTGRES_USER` 保持一致；详见 [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md#数据库命名约定)。

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

## 服务器部署 (阿里云 / 云服务器)

推荐使用一键安装脚本 `scripts/deploy.sh`，支持 Ubuntu 20/22 和 CentOS 7/8：

```bash
# 1. 将代码上传到服务器
git clone <repo_url> /opt/craftifyxminer
cd /opt/craftifyxminer

# 2. 运行一键部署（需要 root 权限）
sudo bash scripts/deploy.sh
```

脚本将自动完成：
1. 安装 Docker + Docker Compose
2. 交互式配置 `.env`（输入 RDS 地址、API Key 等）
3. 自动生成 `FLASK_SECRET_KEY` 和 `JWT_SECRET_KEY`
4. 初始化数据库 schema
5. 创建 Admin 用户
6. 启动 Nginx + Flask + Streamlit + Cron
7. 配置每日 3:00 AM 数据库备份
8. 配置防火墙（仅开放 22/80/443）

部署完成后访问 `http://<服务器IP>` 即可使用 Dashboard。

### HTTPS 配置（可选）

购买域名后，仅需 3 步：
1. DNS A 记录指向服务器 IP
2. 在 `nginx/nginx.conf` 中修改 `server_name`
3. 运行 `certbot --nginx -d yourdomain.com`

### 运维命令

```bash
# 查看日志
docker compose -f docker-compose.prod.yml logs -f

# 重启服务
docker compose -f docker-compose.prod.yml restart

# 手动备份
bash scripts/backup_db.sh

# 用户管理
docker compose -f docker-compose.prod.yml run --rm server python -m auth.manage create-user --username bd1 --password 'SecurePass1'
docker compose -f docker-compose.prod.yml run --rm server python -m auth.manage reset-password --username admin --password 'NewPass123'
docker compose -f docker-compose.prod.yml run --rm server python -m auth.manage unlock --username admin
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
