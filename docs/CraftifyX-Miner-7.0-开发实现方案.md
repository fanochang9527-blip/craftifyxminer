# CraftifyX Miner 7.0 — 完整开发实现方案（国产模型版）

> **版本**：v7.0（2026-03-24）  
> **与 6.0 关系**：本方案在 **Miner 6.0** 的工程设计上迭代，**不推翻重来**：三级数据采集管道、Webhook、`bio_rules` + `ai_filter`、10 维 + SPS、`weights.yaml`、Streamlit 等保持一致；**7.0 增量**主要为：**圈层影响力字段 `circle_influence_score`**（替代 `fan_creator_ratio`）、**BIO 四级产品叙事与可选误杀复盘表**、文档与验收口径统一。  
> **状态**：待确认启动  
> **技术栈**：Python (Flask/aiohttp) + Apify + 国产大模型 (Qwen/DeepSeek/Kimi 等) + PostgreSQL + Streamlit  
> **交付周期**：4 周（MVP）；完整 Multi-hop / 误杀 Few-shot 可列 v1.1  
> **月度预算**：≤$500  
> **决策向说明书**：[CraftifyX-Miner-7.0-项目说明书.md](./CraftifyX-Miner-7.0-项目说明书.md)

---

## 开发任务清单

| ID | 任务 | 阶段 | 状态 |
|----|------|------|------|
| W1-1 | 编写 db/schema.sql (9 张表完整 DDL + 索引) 和 config/settings.py | Week 1 | 待启动 |
| W1-2 | 实现 Flask Webhook 接收端 (server/app.py, server/webhook.py) + Apify Actor 调通 | Week 1 | 待启动 |
| W1-3 | 实现种子导入脚本 (pipeline/seed_import.py) + apify_config.yaml | Week 1 | 待启动 |
| W2-0 | 编写 BIO 知识库配置 (config/bio_rules.yaml: Link DNA 指纹库 + 语义矩阵关键词 + Emoji 信号表 + 误杀防范规则) + 规则快筛模块 (pipeline/bio_rule_filter.py: Level 1/2 正则+关键词匹配) | Week 2 | 待启动 |
| W2-1 | 实现国产大模型 Bio 过滤服务 (pipeline/ai_filter.py, 统一 OpenAI 兼容接口, 支持 Qwen/DeepSeek/Kimi/智谱/MiniMax 五 provider, 优先阿里云百炼网关; System Prompt 融合 BIO 知识库, Level 3 语义兜底) | Week 2 | 待启动 |
| W2-2 | 实现每日发现引擎 (pipeline/discovery.py, 含 10-20% 随机探索三策略) | Week 2 | 待启动 |
| W3-1 | 实现深度抓取触发 (pipeline/deep_scrape.py) + Residential Proxy 配置 | Week 3 | 待启动 |
| W3-2 | 实现 10 维指标计算 + SPS 评分 + 中心度 (feature_engine.py, sps_scorer.py, weights.yaml) | Week 3 | 待启动 |
| W4-1 | 实现 Streamlit Dashboard 4 页面 (日报/候选人/联系追踪/成本监控) | Week 4 | 待启动 |
| W4-2 | 定时任务编排 (cron/daily_job.py) + docker-compose.yml + 部署上线 | Week 4 | 待启动 |
| W4-3 | 飞轮进化简化版 (pipeline/evolution.py, Seed 晋升逻辑) + 联调测试 | Week 4 | 待启动 |
| W4-4 (可选) | 误杀复盘库: `db/migrations` 增加 `missed_gems_library` 表；Dashboard「标记误杀」+ 周更 Few-shot 注入 `ai_filter`（可与 v1.1 合并） | Week 4 或 v1.1 | 待启动 |

---

## 一、项目目录结构

```
craftifyxminer/
├── config/
│   ├── settings.py              # 环境变量与全局配置
│   ├── apify_config.yaml        # Apify Actor 参数
│   ├── weights.yaml             # 5 类创作者 SPS 权重矩阵
│   └── bio_rules.yaml           # BIO 知识库: Link DNA 指纹 + 语义矩阵 + Emoji 信号 + 误杀防范
├── db/
│   ├── schema.sql               # 6+1 张核心表完整 DDL
│   ├── indexes.sql              # 查询优化索引
│   └── seed_import.sql          # 种子导入脚本
├── server/
│   ├── app.py                   # Flask 主应用入口
│   ├── webhook.py               # Apify Webhook 接收路由
│   └── api.py                   # 内部 REST API（触发深度抓取等）
├── pipeline/
│   ├── seed_import.py           # Phase 1: 种子 CSV 导入与 Tier 标记
│   ├── discovery.py             # 每日发现引擎（含 10-20% 随机探索）
│   ├── bio_rule_filter.py       # Level 1/2 规则快筛: 正则匹配 Link DNA + 语义矩阵关键词 + Emoji 信号
│   ├── ai_filter.py             # Level 3 国产大模型 Bio 语义判定（Qwen/DeepSeek/Kimi/智谱/MiniMax）
│   ├── deep_scrape.py           # 二级触发: 过滤通过 -> Apify Deep Scrape
│   ├── feature_engine.py        # 10 维指标计算
│   ├── sps_scorer.py            # SPS 评分 + 中心度分层
│   └── evolution.py             # 飞轮进化（简化: 数据回流 + Seed 晋升）
├── dashboard/
│   ├── app.py                   # Streamlit 主入口
│   ├── pages/
│   │   ├── 1_daily_report.py    # 每日发现报告
│   │   ├── 2_candidates.py      # 候选人浏览与 BD 判定
│   │   ├── 3_outreach.py        # 联系追踪与销售反馈录入
│   │   └── 4_cost_monitor.py    # 成本监控面板
│   └── components/
│       └── radar_chart.py       # 10 维雷达图组件
├── cron/
│   └── daily_job.py             # 定时任务编排（APScheduler）
├── tests/
│   ├── test_bio_rule_filter.py  # BIO 规则快筛单元测试 (Link DNA / 语义矩阵 / 误杀防范)
│   ├── test_ai_filter.py        # AI 过滤单元测试
│   ├── test_feature_engine.py   # 指标计算测试
│   └── test_sps_scorer.py       # SPS 评分测试
├── requirements.txt
├── Dockerfile
├── docker-compose.yml           # PostgreSQL + Flask + Streamlit 一键启动
├── .env.example                 # 环境变量模板
└── README.md                    # 部署与运行说明
```

---

## 二、技术架构总览

```mermaid
graph TB
    subgraph L1_Scan["L1: 浅层扫描 (Datacenter Proxy)"]
        SeedDB["Seed 库\n80% 高价值 + 20% 随机探索"]
        ApifyScan["Apify Following Actor\nDatacenter Proxy $0.3/GB"]
        Webhook["Flask Webhook\n/apify-webhook"]
        SeedDB --> ApifyScan
        ApifyScan -->|"ACTOR.RUN.SUCCEEDED"| Webhook
    end

    subgraph L2_Filter["L2: AI 预过滤 (国产大模型)"]
        BioQueue["Raw Bio 队列\n~5000/日"]
        LLMGateway["阿里云百炼 OpenAI 兼容网关\nQwen/DeepSeek 主力\nKimi/智谱/MiniMax 备选\n并发 50, ~$0.1/日"]
        Candidates["过滤后候选\n500-800/日"]
        Webhook --> BioQueue
        BioQueue --> LLMGateway
        LLMGateway --> Candidates
    end

    subgraph L3_Deep["L3: 深度抓取 (Residential Proxy)"]
        DeepScrape["Apify Deep Actor\nProfile + 10 Tweets\nResidential $8-12/GB"]
        FeatureCalc["10 维指标计算"]
        SPSScore["SPS 评分 + 中心度"]
        Candidates --> DeepScrape
        DeepScrape --> FeatureCalc
        FeatureCalc --> SPSScore
    end

    subgraph App["应用层"]
        Dashboard["Streamlit Dashboard"]
        BDFlow["BD 判定流程\nInterested/Rejected/Deferred"]
        CostPanel["成本监控面板"]
        SPSScore --> Dashboard
        Dashboard --> BDFlow
        Dashboard --> CostPanel
    end

    subgraph Evolution["进化层 (7.0: 双轨 + 可选误杀)"]
        SalesFB["Sales Feedback 录入"]
        SeedPromotion["Seed 晋升\nGMV > $1000"]
        MissedGems["可选: Missed Gems\n→ Few-shot 注入 ai_filter"]
        BDFlow --> SalesFB
        BDFlow -.-> MissedGems
        SalesFB --> SeedPromotion
        SeedPromotion --> SeedDB
    end
```

---

## 三、开发环境准备

### 3.1 第三方服务申请

- **Apify**
  - 注册: https://console.apify.com/sign-up
  - 订阅 Starter 计划 ($49/月, 含 100 Actor runs, 代理流量按用量计费)
  - 获取 API Token: Console -> Settings -> Integrations -> API token
  - 所需 Actor:
    - `apidojo/tweet-scraper` (Profile + Tweets)
    - `apidojo/twitter-scraper-v2` (Following/Followers)
    - 或使用 `curious_coder/twitter-scraper` 等社区 Actor

- **阿里云百炼 (统一网关, 首选接入方式)**
  - 注册: https://bailian.console.aliyun.com/ (需阿里云账号)
  - 开通百炼服务 -> 获取 API Key (即 DASHSCOPE_API_KEY)
  - 优势: 一个 Key 调用多家模型 (Qwen 全系列 + DeepSeek V3.2 + Kimi + GLM + MiniMax)
  - OpenAI 兼容 base_url: `https://dashscope.aliyuncs.com/compatible-mode/v1`
  - Batch API (50% 折扣): `https://batch.dashscope.aliyuncs.com/compatible-mode/v1`
  - 新用户免费额度: 千万 tokens
  - 注意: Coding Plan 是 IDE 编程套餐, 禁止 API 调用, 不适用本场景; 我们使用按量付费 API

- **通义千问 Qwen (主力模型 A, 通过百炼调用)**
  - 模型选择:
    - `qwen-turbo` -- 极致低价, 输入 ¥0.0003/千tokens, 输出 ¥0.0006/千tokens, 适合 Bio 过滤
    - `qwen3.5-flash` -- 性能更强, 价格略高
    - `qwen3.5-plus` -- 输入 ¥1.52/百万tokens, 输出 ¥3.8/百万tokens
  - 日成本估算 (5000 Bio x ~120 tokens/次): qwen-turbo 约 ¥0.04/日 ≈ $0.006/日

- **DeepSeek (主力模型 B, 可通过百炼或直连)**
  - 百炼调用: 模型名 `deepseek-v3.2`, 同一个 DASHSCOPE_API_KEY
  - 直连: https://platform.deepseek.com/ , 模型 `deepseek-chat`
  - 价格: 输入 ¥0.2/百万tokens, 输出 ¥3/百万tokens (直连); 百炼价格可能略有不同
  - 日成本估算: ~$0.18/日
  - 模型优先级: Qwen 和 DeepSeek 并行测试, 按实际过滤准确率确定默认模型

- **Kimi / Moonshot (备选 1)**
  - 百炼调用: 模型名 `kimi-k2.5` (如百炼已上架)
  - 直连: https://platform.moonshot.cn/ , base_url `https://api.moonshot.cn/v1`
  - API 兼容 OpenAI SDK, 切换 base_url 即可
  - 价格: 输入 $0.60/百万tokens, 输出 $2.50/百万tokens (较贵, 作为备选)

- **智谱 GLM (备选 2)**
  - 百炼调用: 模型名 `glm-5` 或 `glm-4-flash` (如百炼已上架)
  - 直连: https://open.bigmodel.cn/ , base_url `https://open.bigmodel.cn/api/paas/v4`
  - API 兼容 OpenAI SDK
  - `glm-4-flash` 有大量免费额度, 适合开发期测试

- **MiniMax (备选 3)**
  - 百炼调用: 模型名 `minimax-m2.5` (如百炼已上架)
  - 直连: https://platform.minimaxi.com/ , 需单独注册
  - 价格: M2.1 输入 ¥2.1/百万tokens, 输出 ¥8.4/百万tokens
  - 付费用户默认 500 RPM, 并发能力强

- **PostgreSQL**
  - 方案 A (推荐): 阿里云 RDS PostgreSQL 基础版 2C4G 100GB -- ¥228/年 (~$2.6/月), 自动备份, 免运维
    - 购买: https://rdsbuy.console.aliyun.com/ -> 选择 PostgreSQL -> 基础版
  - 方案 B (省钱): 在阿里云/腾讯云轻量服务器上 Docker 自建 PostgreSQL -- $0 额外费用
    - 适合初期数据量小 (<1GB) 的场景, 需自行备份
  - 方案 C (腾讯云): 云数据库 PostgreSQL 基础版 -- ~¥250/年
    - 购买: https://console.cloud.tencent.com/postgres
  - 方案 D (第三方): Supabase Free (500MB) 或 Neon Free (0.5GB) -- $0
    - Supabase: https://supabase.com (7 天不活跃会暂停, 需保活)
    - Neon: https://neon.tech (Serverless, 自动 scale-to-zero, 100 CU-hours/月)
    - 适合原型验证; 生产环境建议用方案 A/B

### 3.2 本地开发环境

- Python 3.11+
- PostgreSQL 18+ (本地或 Docker，`docker-compose.yml` 默认 `postgres:18-alpine`)
- 依赖见 `requirements.txt`:

```
flask==3.1.*
aiohttp==3.11.*
asyncio
asyncpg==0.30.*
psycopg2-binary==2.9.*
sqlalchemy==2.0.*
openai==1.66.*                  # 统一 LLM 调用 (所有 provider 均走 OpenAI 兼容接口)
apify-client==1.8.*
streamlit==1.41.*
plotly==6.0.*
pandas==2.2.*
pyyaml==6.0.*
python-dotenv==1.0.*
apscheduler==3.10.*
httpx==0.28.*
```

### 3.3 环境变量 (`.env.example`)

```env
# PostgreSQL
DATABASE_URL=postgresql://user:password@localhost:5432/craftifyx_miner

# Apify
APIFY_API_TOKEN=apify_api_xxxxxxxx
APIFY_WEBHOOK_SECRET=your_webhook_secret

# === 国产大模型配置 ===
# 统一网关: 阿里云百炼 (推荐, 一个 Key 调多家模型)
DASHSCOPE_API_KEY=sk-xxxxxxxx
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# Batch API (非实时场景, 半价): https://batch.dashscope.aliyuncs.com/compatible-mode/v1

# 主力模型 (优先长上下文, 按测试效果确认)
LLM_PROVIDER=moonshot
LLM_MODEL=kimi-k2.5
# 可选值: kimi-k2.5 (256K, Moonshot) / qwen3.5-plus (256K, 百炼) / deepseek-v3.2 (128K, 百炼)
LLM_BATCH_SIZE=50           # 批量模式: 一次处理 50 条 Bio

# 备选: DeepSeek 直连 (百炼不可用时 fallback)
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# 备选: Kimi/Moonshot 直连
MOONSHOT_API_KEY=sk-xxxxxxxx
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1

# 备选: 智谱 GLM 直连
ZHIPU_API_KEY=xxxxxxxx
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4

# 备选: MiniMax 直连
MINIMAX_API_KEY=xxxxxxxx
MINIMAX_BASE_URL=https://api.minimax.chat/v1

# Flask
FLASK_SECRET_KEY=xxx
FLASK_PORT=5000

# Streamlit
STREAMLIT_PORT=8501

# 成本控制
DAILY_APIFY_BUDGET_USD=20
MONTHLY_LLM_BUDGET_USD=10
```

---

## 四、数据库设计 -- 9 张核心表 + 7.0 可选表

完整 SQL 写入 `db/schema.sql`，核心设计要点:

- `creators` 表增加 `discovery_strategy` 字段 (区分常规/地域探索/标签探索/时间探索)
- `creator_features` 用 UNIQUE(creator_id) 约束保证一对一最新快照；**第 7 维为 `circle_influence_score`（圈层影响力，Miner 7.0），已替代 `fan_creator_ratio`**
- `creator_graph` 添加复合索引 `(connected_creator_id, creator_id)` 支撑中心度与 `seed_connections` 查询
- `creator_scores` 含 `seed_connections`、`centrality_tier`，与 `circle_influence_score` 同源
- `outreach_log` 和 `sales_feedback` 通过 `creator_id` 外键关联
- `cost_tracking`、`discovery_batches` 见下

表结构以仓库 `db/schema.sql` 为准；以下为历史文档中「额外增加」的片段，**与当前 schema 合并理解即可**:

```sql
-- 8. cost_tracking (成本监控)
CREATE TABLE cost_tracking (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    apify_cu_used FLOAT DEFAULT 0,
    apify_cost_usd FLOAT DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0,
    llm_cost_usd FLOAT DEFAULT 0,
    proxy_datacenter_gb FLOAT DEFAULT 0,
    proxy_residential_gb FLOAT DEFAULT 0,
    proxy_cost_usd FLOAT DEFAULT 0,
    total_cost_usd FLOAT DEFAULT 0,
    UNIQUE(date)
);

-- 9. discovery_batches (发现批次追踪)
CREATE TABLE discovery_batches (
    id SERIAL PRIMARY KEY,
    batch_date DATE NOT NULL DEFAULT CURRENT_DATE,
    batch_type VARCHAR(20),       -- 'daily_l1', 'daily_l2', 'reverse', 'explore'
    anchor_seeds TEXT[],
    exploration_ratio FLOAT,
    raw_discovered INTEGER DEFAULT 0,
    after_ai_filter INTEGER DEFAULT 0,
    after_deep_scrape INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Miner 7.0 可选（误杀复盘，W4-4 / v1.1）**：

```sql
-- 可选第 10 张表：与 MVP 9 表独立迁移，避免阻塞首期上线
CREATE TABLE IF NOT EXISTS missed_gems_library (
    id SERIAL PRIMARY KEY,
    bio_text TEXT NOT NULL,
    rejection_reason VARCHAR(200),
    actual_type VARCHAR(50),
    gmv_generated FLOAT,
    added_by VARCHAR(80),
    used_in_training BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### BIO：产品「四级」与工程「Level 1/2/3」的对应关系

| 产品叙事（7.0 对外） | 工程实现 |
|---------------------|----------|
| Level A：硬规则 / Link DNA | `bio_rules.yaml` 中 `link_dna` + 规则引擎优先匹配 |
| Level B：语义矩阵 | `semantic_matrix` + Emoji |
| Level C：LLM | `ai_filter.py` 批量灰区 |
| Level D：误杀复盘 | `missed_gems_library` + Prompt 周更（可选） |

工程上仍称 **Level 1/2 = 规则快筛、Level 3 = LLM**，与说明书「三级管道（L1/L2/L3 采集）」不是同一概念。

---

## 五、分周开发实现

### Week 1: 管道搭建 + 数据基座 (Pipe-First)

**核心目标**: 数据库就绪、Webhook 接收端可用、种子导入完成、Apify 首次调通

#### 1.1 数据库建表与种子导入

- **文件**: `db/schema.sql`, `pipeline/seed_import.py`
- **核心逻辑**: 读取 `merged_creators.csv`，按 `total_sales` 打 Tier 标签 (S/A/B/C)，写入 `creators` 表并标记 `is_seed=true`
- Tier 划分规则: S (>$2000), A (>$500), B (>$100), C (其余)

#### 1.2 Flask Webhook 接收端

- **文件**: `server/app.py`, `server/webhook.py`
- **核心逻辑**: 监听 `/apify-webhook` POST 请求，校验 `X-Apify-Webhook-Secret`，解析 `resource.defaultDatasetId`，将 raw following 数据存入 `creators` 表 (bio + basic info)，同时将需要 AI 过滤的 bio 推入内存队列
- Apify Webhook 配置步骤:
  1. 进入 Apify Console -> Actor -> Settings -> Integrations
  2. 添加 Webhook URL: `https://your-server.railway.app/apify-webhook`
  3. 事件类型: `ACTOR.RUN.SUCCEEDED`
  4. 附加 Payload template: `{"datasetId": "{{resource.defaultDatasetId}}", "actorRunId": "{{resource.id}}"}`

#### 1.3 Apify Actor 首次调通

- **文件**: `config/apify_config.yaml`
- 配置 Following Actor 参数:

```yaml
following_actor:
  actor_id: "apidojo/twitter-scraper-v2"
  input:
    action: "following"
    handles: []          # 由代码动态填入
    max_items: 500
    proxy:
      useApifyProxy: true
      apifyProxyGroups: ["DATACENTER"]  # L1 用 Datacenter
```

- 使用 `apify-client` Python SDK 触发 Actor run，验证数据回流

#### Week 1 测试要点

- PostgreSQL 连接与全部 9 张表创建成功
- CSV 导入 100 个种子，Tier 分布符合预期
- 手动触发 1 个 Apify Following run，Webhook 成功接收数据并入库
- Flask 服务本地启动正常，Webhook 端点返回 200

#### Week 1 产出物

- `db/schema.sql` -- 可直接执行的完整 DDL
- `server/app.py` + `server/webhook.py` -- Webhook 接收端
- `pipeline/seed_import.py` -- 种子导入脚本
- `config/apify_config.yaml` -- Actor 配置
- `config/settings.py` -- 环境变量加载

---

### Week 2: BIO 知识库 + 国产大模型 AI 预过滤 + Seed 库随机探索

**核心目标**: BIO 规则快筛模块可用、LLM 批量过滤服务可用、随机探索 Seed 选择算法就绪

#### 2.0 BIO 知识库配置 + 规则快筛模块（Level 1 / Level 2）

- **文件**: `config/bio_rules.yaml`（知识库配置）, `pipeline/bio_rule_filter.py`（规则快筛引擎）
- **背景**: 实际数据表明大量创作者 BIO 不含 "Artist" 字样，但有独特的链接指纹、Emoji 组合和行业术语。基于数百名已验证创作者的 BIO 特征提取，构建三级校验的前两级（零 LLM 成本）

- **`config/bio_rules.yaml` 知识库结构**:

```yaml
# === Level 1: Link DNA 指纹 (出现即 95%+ 为创作者) ===
link_dna:
  high_confidence:    # 任一匹配 → 直接 YES
    - "linktr.ee"
    - "linktree.com"
    - "carrd.co"
    - "carrd.me"
    - "artstation.com"
    - "pixiv.net"
    - "pixiv.me"
    - "booth.pm"
    - "vgen.co"
    - "vgen.ai"
    - "toyhou.se"
    - "deviantart.com"
    - "etsy.com/shop"
    - "gumroad.com"
    - "ko-fi.com"
    - "patreon.com"
  medium_confidence:  # 需配合其他信号
    - "twitch.tv"
    - "youtube.com/@"
    - "instagram.com/"

# === Level 2: 语义矩阵 ===
semantic_matrix:
  identity_keywords:    # 身份类 (任一命中 → YES)
    en:
      - "illustrator"
      - "artist"
      - "artisan"
      - "character designer"
      - "character creator"
      - "fanartist"
      - "plush artist"
      - "doll maker"
      - "game dev"
      - "indie dev"
      - "vtuber designer"
    ja:
      - "絵師"
      - "イラストレーター"
    zh:
      - "画师"
      - "插画师"
      - "原画师"
      - "概念艺术家"
      - "角色设计师"
      - "毛绒设计师"
      - "同人艺术家"
      - "独立游戏画师"

  action_keywords:      # 动作类 (商品化/预售信号)
    en:
      - "commission open"
      - "comm open"
      - "preorder"
      - "pre-order"
      - "shop now"
      - "new drop"
      - "merch"
    zh:
      - "接稿"
      - "开预售"
      - "众筹"
      - "贩售"
      - "定制"
      - "商品化"

  weak_signals:         # 弱信号 (需 2+ 命中才判 YES)
    - "OC"
    - "original character"
    - "fanart"
    - "doujin"
    - "VTuber"
    - "Repost OK"
    - "RT OK"
    - "shop"
    - "store"
    - "work"

  tool_keywords:        # 工具类 (专业创作者工具链)
    - "Procreate"
    - "Clip Studio"
    - "CSP"
    - "Photoshop"
    - "Blender"
    - "Live2D"
    - "Wacom"
    - "SAI"

# === Emoji 信号 ===
emoji_signals:
  creative:  ["🎨", "🖌️", "✍️", "📝"]
  character: ["🐰", "🦊", "🐱", "🐻", "🌸", "✨", "⭐"]
  commerce:  ["🛍️", "💰", "🛒", "📦"]
  craft:     ["🔨", "🛠️"]

# === 误杀防范 ===
false_positive_rules:
  fan_account_signals:  # 纯粉丝号特征 → 排除
    - "fan account"
    - "fan page"
    - "stan account"
  studio_signals:       # 工作室号 (标记为 studio 而非个人创作者)
    - "team"
    - "studio"
    - "agency"
    - " we "

# === 创作者类型标签 (用于 SPS 权重选择) ===
type_classification:
  oc_creator:     ["OC", "original character", "my OC", "OC art"]
  vtuber:         ["VTuber", "virtual youtuber", "虚拟主播", "Live2D"]
  fan_artist:     ["fanart", "doujin", "二次创作", "同人"]
  game_creator:   ["indie game", "game dev", "indie studio"]
  content_creator: ["art blog", "daily art", "sketchbook"]
```

- **`pipeline/bio_rule_filter.py` 核心逻辑**:

```python
import re, yaml

class BioRuleFilter:
    """Level 1/2 规则快筛: 零 LLM 成本, 处理 ~70% 的明确 case"""

    def __init__(self, rules_path="config/bio_rules.yaml"):
        with open(rules_path) as f:
            self.rules = yaml.safe_load(f)
        self._compile_patterns()

    def filter(self, bio: str, website: str = "") -> dict:
        """
        返回: {"passed": bool, "level": 1|2|0, "type": str|None, "confidence": float, "signals": list}
        level=0 表示规则未命中, 需交给 Level 3 LLM 判定
        """
        text = f"{bio} {website}".lower()

        # Level 1: Link DNA
        link_signals = [d for d in self.rules["link_dna"]["high_confidence"] if d in text]
        if link_signals:
            return {"passed": True, "level": 1, "type": self._classify_type(text),
                    "confidence": 0.95, "signals": link_signals}

        # Level 2: 语义矩阵
        identity_hits = self._match_keywords(text, "identity_keywords")
        action_hits = self._match_keywords(text, "action_keywords")
        tool_hits = self._match_keywords(text, "tool_keywords")
        weak_hits = self._match_keywords(text, "weak_signals")
        emoji_hits = self._match_emojis(bio)

        # 身份类命中 → 直接 YES
        if identity_hits:
            return {"passed": True, "level": 2, "type": self._classify_type(text),
                    "confidence": 0.90, "signals": identity_hits}
        # 动作+工具 或 弱信号 2+ 命中 → YES
        if (action_hits and tool_hits) or len(weak_hits) >= 2 or (action_hits and emoji_hits):
            return {"passed": True, "level": 2, "type": self._classify_type(text),
                    "confidence": 0.80, "signals": action_hits + tool_hits + weak_hits}

        # 误杀检测
        if self._is_false_positive(text):
            return {"passed": False, "level": 2, "type": None, "confidence": 0.85, "signals": ["false_positive"]}

        # 规则未命中 → 交给 Level 3 LLM
        return {"passed": None, "level": 0, "type": None, "confidence": 0.0,
                "signals": weak_hits + emoji_hits}
```

- **与 AI Filter 的衔接**: `bio_rule_filter` 先跑, 结果为 `passed=True` 直接入库, `passed=False` 直接淘汰, `passed=None` 的灰区 BIO 推入 LLM 批量队列

#### 2.1 国产大模型 Bio 过滤服务（Level 3 语义兜底）

- **文件**: `pipeline/ai_filter.py`
- **核心架构**: 所有模型统一通过 OpenAI SDK 兼容接口调用, 仅切换 `base_url` + `api_key` + `model` 三个参数
- **定位**: 处理 Level 1/2 规则快筛未能覆盖的灰区 BIO（约占总量 30%），大幅降低 LLM 调用成本

- **模型优先级**: 优先使用 **Kimi K2.5** 或 **Qwen3.5-Plus** 等长上下文模型（256K），利用长上下文能力一次请求批量处理 50 条 Bio，提升分类准确率并减少请求次数

- **Provider 配置表** (全部兼容 OpenAI chat/completions 接口，按优先级排列):

| 优先级 | Provider | base_url | 推荐模型 | 上下文 | 输入价格/百万tokens | 日成本 (5000 Bio) |
|--------|----------|----------|----------|--------|-------------------|-----------------|
| 1 (主力) | Kimi 直连 | `api.moonshot.cn/v1` | `kimi-k2.5` | **256K** | $0.60 | ~$0.61 (~$18/月) |
| 1 (主力) | 阿里云百炼 | `dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3.5-plus` | **256K** | ¥1.52 (~$0.21) | ~$0.18 (~$5.4/月) |
| 2 (备选) | 阿里云百炼 | 同上 | `deepseek-v3.2` | 128K | 按百炼定价 | ~$0.1 |
| 3 (备选) | 智谱直连 | `open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | 128K | 免费额度大 | ~$0 (免费期) |
| 4 (备选) | MiniMax 直连 | `api.minimax.chat/v1` | `MiniMax-Text-01` | 128K | ¥2.1 | ~$0.18 |

  - Kimi 和 Qwen3.5-Plus **并行测试**，按准确率和延迟确定默认主力
  - Kimi 费用稍高 (~$18/月) 但仍在 LLM 预算 ($20/月) 内
  - Qwen3.5-Plus 性价比更优 (~$5.4/月)，如果准确率接近则优先选择

- **长上下文批量处理策略**:
  - 单次请求塞入 50 条 Bio（每条 ~100 tokens，50 条 ~5000 tokens + Prompt ~500 tokens，远小于 256K 上限）
  - 一次返回 50 条判断结果，减少请求次数 50 倍（5000 Bio 仅需 100 次请求）
  - 模型可在同一批次内对比不同 Bio，提升边界 case 的分类准确率
  - 批量 Prompt 模板输出格式改为 JSON 数组，便于解析

- **核心设计**:
  - 统一 `LLMClient` 类, 构造函数接受 `(base_url, api_key, model)`, 内部使用 `openai.AsyncOpenAI` 异步客户端
  - **主路径**: Kimi K2.5 或百炼 Qwen3.5-Plus（按测试结果确定）
  - **降级链**: Kimi K2.5 -> 百炼 Qwen3.5-Plus -> 百炼 DeepSeek -> 智谱 GLM（按可用性自动切换）
  - 异步并发: `asyncio.Semaphore(10)` 控制并发（批量模式下每次 50 条，10 并发 = 500 条同时处理）
  - Prompt 模板: System Prompt 融合 BIO 知识库中的 Link DNA / 语义矩阵 / Emoji 信号作为判断依据 + 批量判断是否创作者 + 输出 JSON 数组 `[{"bio_id":1,"result":"YES","type":"OC","confidence":0.95}, ...]`
  - 错误重试: 3 次指数退避, 第 3 次失败切换到降级 provider
  - 成本追踪: 从 response.usage 读取 token 数, 写入 `cost_tracking` 表

- **统一调用代码骨架** (批量模式):

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=os.getenv("MOONSHOT_API_KEY"),  # 或 DASHSCOPE_API_KEY
    base_url="https://api.moonshot.cn/v1"   # 或百炼 URL
)

# 批量 Prompt: 一次处理 50 条 Bio
batch_prompt = BATCH_FILTER_PROMPT.format(bios=json.dumps(bio_batch, ensure_ascii=False))
resp = await client.chat.completions.create(
    model="kimi-k2.5",  # 或 qwen3.5-plus
    messages=[{"role": "user", "content": batch_prompt}],
    temperature=0.1,
    max_tokens=2000,     # 50 条结果需要更多输出 tokens
    response_format={"type": "json_object"}  # 强制 JSON 输出
)
results = json.loads(resp.choices[0].message.content)  # 解析 50 条结果
tokens_used = resp.usage.total_tokens
```

- **模型选型测试计划** (Week 2 内完成):
  1. 准备 100 条标注 Bio 测试集 (50 真创作者 + 50 非创作者)
  2. 分别测试: **Kimi K2.5 (批量50)**, **Qwen3.5-Plus (批量50)**, DeepSeek V3.2 (逐条) 三种模式
  3. 对比: 准确率、延迟 (P50/P99)、token 消耗、每条 Bio 平均成本
  4. 验证批量模式 vs 逐条模式的准确率差异
  5. 确定默认主力模型（暂定 Kimi 或 Qwen3.5-Plus，按测试结果）

#### 2.2 Seed 库管理与随机探索

- **文件**: `pipeline/discovery.py`
- **核心逻辑** (参考文档 [docs/apify.md](apify.md) 第 154-198 行):
  - `generate_daily_seeds()`: 80% 高价值 (Tier S/A, 按 `last_used_as_anchor` 升序轮换) + 20% 随机探索
  - 随机探索三策略: 跨地域 (`#絵描きさんと繋がりたい` 等日/韩标签)、跨品类 (`#indiegame`, `#gamedev`)、时间随机 (老账号挖掘)
  - 每个候选人标记 `discovery_strategy` 字段: `seed_following` / `geo_explore` / `hashtag_explore` / `time_explore`
  - 写入 `discovery_batches` 表记录探索比例

#### 2.3 Webhook 到过滤的自动流转（三级管道）

- 修改 `server/webhook.py`: 接收 raw following 数据后，按三级管道处理:
  1. **Level 1/2 规则快筛** (`bio_rule_filter.filter()`): 零成本处理 ~70% 明确 case
     - `passed=True` → 直接写入 `creators` 表 (状态 `rule_passed`)
     - `passed=False` → 标记 `rule_rejected`
     - `passed=None` → 推入 LLM 批量队列
  2. **Level 3 LLM 语义判定** (`ai_filter.filter_batch()`): 仅处理灰区 BIO (~30%)
     - 过滤通过 → 状态 `ai_passed`
     - 不通过 → 状态 `ai_rejected`
- 效果: LLM 调用量降至原来的 ~30%, 月成本从 $5-20 进一步降至 $2-6

#### Week 2 测试要点

- 准备 100 条标注 Bio (含 50 真创作者 + 50 非创作者) 测试集
- **规则快筛准确率**: Level 1/2 在 100 条测试集上的精确率 >95%, 召回率 >60% (即能零成本覆盖 60%+ 的真创作者)
- **三级联合准确率**: Level 1/2 + Level 3 联合准确率 >90%
- 分别测试 Kimi K2.5 (批量50)、Qwen3.5-Plus (批量50)、DeepSeek V3.2 (逐条): P99 延迟 <5s (批量)
- 批量模式 JSON 输出解析稳定性验证（50 条 Bio 一次返回，解析成功率 >99%）
- 降级链路测试 (模拟主 provider 返回 429 后自动切换)
- 随机探索比例验证: 生成 20 个锚点, 其中 4 个来自探索策略
- 成本记录: 验证规则快筛后 LLM 调用量降至原来的 ~30%, 月成本 <$10
- 输出模型选型报告: 确定默认主力模型 (Kimi vs Qwen3.5-Plus)

#### Week 2 产出物

- `config/bio_rules.yaml` -- BIO 知识库配置 (Link DNA + 语义矩阵 + Emoji 信号 + 误杀防范)
- `pipeline/bio_rule_filter.py` -- Level 1/2 规则快筛模块
- `pipeline/ai_filter.py` -- Level 3 国产大模型过滤服务 (统一 OpenAI 兼容接口, 含 Qwen/DeepSeek/Kimi/智谱/MiniMax 五 provider + 降级链)
- `pipeline/discovery.py` -- 每日发现引擎 (含随机探索)
- `tests/test_bio_rule_filter.py` -- 规则快筛单元测试 (Link DNA / 语义矩阵 / 误杀防范)
- `tests/test_ai_filter.py` -- 多模型过滤准确率对比测试
- 模型选型测试报告 (准确率/延迟/成本对比表)

---

### Week 3: 深度抓取 + 10 维指标 + SPS 评分

**核心目标**: 三级管道完整跑通，每日产出 300-500 个带 SPS 评分的候选人

#### 3.1 深度抓取触发

- **文件**: `pipeline/deep_scrape.py`
- **核心逻辑**: AI 过滤通过的候选人 -> 触发 Apify Deep Scrape Actor
  - Actor 配置切换 Residential Proxy: `apifyProxyGroups: ["RESIDENTIAL"]`
  - 抓取内容: Profile 完整信息 + 最近 10 条 Tweets (含 likes/retweets/replies/views)
  - 数据回写: `creators` 表更新完整 profile，`tweets` 表写入推文数据
  - 批量触发: 每次 50 人一批，控制 Apify 并发 Actor runs

#### 3.2 10 维指标计算引擎

- **文件**: `pipeline/feature_engine.py`
- **10 维指标计算公式** (基于文档 [docs/CraftifyX-Miner-6.0.md](CraftifyX-Miner-6.0.md) 第 284-295 行):

| 指标 | 计算方式 |
|------|----------|
| Audience | `min(log10(followers+1) * 20, 100)` |
| Engagement | `min((avg_likes + avg_rt*2 + avg_replies*3) / followers * 100, 100)` |
| Virality | `min(top3_avg / monthly_avg, 10) * 10` (>5x 满分) |
| Posting | `min(monthly_posts / 30 * 100, 100)` |
| Monetization | 复用 `bio_rules.yaml` 中的 Link DNA + 动作关键词: 有 `booth.pm`/`etsy.com/shop`/`gumroad.com` 等商品链接→90, 有 `commission open`/`preorder`/`接稿` 等动作词→60, 仅有 `shop`/`store`/🛍️ 等弱信号→30, 无→0 |
| Growth | 基于 30 天粉丝增长率 (初版简化: 无历史数据时用 0.5 占位) |
| Circle Influence Score（圈层影响力） | 与 Miner 7.0 一致，**替换原 fan_creator_ratio**。先算 `seed_connections`：在 `creator_graph` 中，有多少个 `is_seed=true` 的 `creator_id` 以 `follow`（或等价边）指向该候选人 `connected_creator_id`。写入 `creator_scores.seed_connections` 与分层 Hub/Connector/Peripheral；再写入 `creator_features.circle_influence_score = min(100, seed_connections × 20)`（0 个→0，5 个及以上→100）。**不**再使用粉丝抽样占比。 |
| Character Consistency | 初版简化: 统计推文中图片 URL 的域名集中度作为代理指标 |
| Community | `min((mentions*2 + fanart_count*5) / max_community * 100, 100)` |
| Data Confidence | `min(account_age_years * 0.6 + profile_completeness * 0.4, 1.0) * 100` |

- 结果写入 `creator_features` 表

#### 3.3 SPS 评分 + 中心度

- **文件**: `pipeline/sps_scorer.py`, `config/weights.yaml`
- **权重矩阵** (5 类创作者不同权重，初版静态配置):

权重键名与 `creator_features` 列一致，含 `growth` 与 `circle_influence_score`（见 `config/weights.yaml` 完整矩阵）：

```yaml
oc_creator:
  audience: 0.10
  engagement: 0.15
  virality: 0.10
  posting: 0.05
  monetization: 0.20
  growth: 0.05
  circle_influence_score: 0.05
  character_consistency: 0.20
  community: 0.05
  data_confidence: 0.05
# vtuber / fan_artist / game_creator / content_creator 见 weights.yaml
```

- SPS = sum(weight_i * score_i) for 10 dimensions（含 `circle_influence_score`）
- 中心度: 与圈层影响力同源指标 `seed_connections` -> Hub(>=5) / Connector(2-4) / Peripheral(0-1)；雷达第 7 维为该值的 0–100 归一化，**不再**使用 `fan_creator_ratio`
- 结果写入 `creator_scores` 表

#### Week 3 测试要点

- 端到端测试: 输入 10 个种子 -> Following 扫描 -> AI 过滤 -> 深度抓取 -> 指标计算 -> SPS 评分
- 验证 SPS 分布: 种子的 SPS 应 >70 (已知高质量)
- 中心度计算: 验证被 5+ Seed 关注的创作者确实标为 Hub
- 单日模拟: 5000 raw -> 500 AI 通过 -> 300-500 深度抓取完成

#### Week 3 产出物

- `pipeline/deep_scrape.py` -- 深度抓取触发
- `pipeline/feature_engine.py` -- 10 维指标
- `pipeline/sps_scorer.py` -- SPS + 中心度
- `config/weights.yaml` -- 静态权重配置
- `tests/test_feature_engine.py`, `tests/test_sps_scorer.py`

---

### Week 4: BD Dashboard + 成本监控 + 联调部署

**核心目标**: Streamlit Dashboard 可用，BD 可进行日常操作，成本可监控

#### 4.1 Streamlit BD Dashboard

- **文件**: `dashboard/app.py` 及 `dashboard/pages/` 下 4 个页面

- **Page 1: 每日发现报告** (`1_daily_report.py`)
  - 今日新候选数、Hub/Connector/Peripheral 分布、SPS>75 筛选数
  - 本周趋势折线图
  - 常规发现 vs 随机探索占比饼图 (绿/蓝/黄/紫四色区分)

- **Page 2: 候选人浏览与 BD 判定** (`2_candidates.py`)
  - 筛选器: 中心度层级、SPS 范围、创作者类型、发现策略
  - 候选人卡片: 头像占位 + @username (外链 X 主页) + 中心度标签 + SPS 分数 + 创作者类型 + 10 维雷达图（**第 7 维：circle_influence_score**）
  - 关键信号: has_merch_experience、Virality 倍数、发现来源
  - 操作按钮: Interested / Rejected / Deferred + 备注输入
  - **7.0 可选**: 「标记误杀」→ 写入 `missed_gems_library`（与 W4-4 联动）
  - 操作结果写入 `creators.bd_decision` 和 `creators.bd_decision_note`

- **Page 3: 联系追踪与销售反馈** (`3_outreach.py`)
  - Interested 创作者列表，记录联系渠道 (email/DM)、联系时间、回复状态
  - 写入 `outreach_log` 表
  - Sales Feedback 录入: GMV、units_sold、launch_date
  - GMV > $1000 时提示 "可晋升为 Seed"，一键操作更新 `creators.is_seed = true`

- **Page 4: 成本监控** (`4_cost_monitor.py`)
  - 本日/本月各项成本 (Apify CU、LLM tokens、代理流量)
  - 预算消耗进度条 ($500/月)
  - 日均成本趋势图
  - 超预算预警 (日超 $25 或月累计超 $400 时红色警告)

- **雷达图组件**: `dashboard/components/radar_chart.py`, 使用 Plotly `go.Scatterpolar`

#### 4.2 定时任务编排

- **文件**: `cron/daily_job.py`
- 使用 APScheduler:
  - 08:00 -- 生成当日锚点 (`discovery.generate_daily_seeds()`)
  - 08:10 -- 触发 Apify L1 扫描 (`discovery.trigger_l1_scan()`)
  - (Webhook 回调后自动) -- AI 过滤 -> 深度抓取 -> 指标计算 -> SPS 评分
  - 23:00 -- 生成日报数据、更新成本统计

#### 4.3 飞轮进化 (简化版)

- **文件**: `pipeline/evolution.py`
- 初版实现: 仅做数据回流 + Seed 自动晋升
  - 当 `sales_feedback.gmv > 1000` 时，将对应创作者 `is_seed` 设为 true, `seed_tier` 设为 'C'
  - 月度报告: 统计各 Tier 的联系成功率、成交率
- 初版暂不实现: XGBoost 权重重训练、LogisticRegression Contact 模型 (标注为 v1.1 迭代项)

#### Week 4 测试要点

- Dashboard 4 个页面均可正常加载与交互
- BD 判定操作 (Interested/Rejected/Deferred) 正确写入数据库
- Sales Feedback 录入后触发 Seed 晋升逻辑
- 成本面板数据与实际 Apify/LLM 消耗一致
- 全链路联调: 种子 -> L1 扫描 -> AI 过滤 -> 深度抓取 -> 评分 -> Dashboard 展示

#### Week 4 产出物

- `dashboard/` 全部代码
- `cron/daily_job.py`
- `pipeline/evolution.py`
- `docker-compose.yml` -- 一键启动
- `README.md` -- 部署与运行说明

---

## 六、系统联调测试

### 全链路测试方案

1. **冒烟测试** (半天): 10 个种子 -> 全流程跑通 -> Dashboard 可见
2. **容量测试** (1 天): 模拟日常 20 锚点 x 500 Following = 10000 raw -> 验证 AI 过滤吞吐 (5000/小时) -> 深度抓取 300-500 -> SPS 分布合理
3. **成本验证** (3 天): 连续 3 天真实运行，核对 Apify/LLM 日成本是否在 $15-20 范围
4. **BD 流程验证**: 产品/BD 人员实际操作 Dashboard，反馈 UI/UX 问题

### 关键验收标准

- 日发现量: 300-500 名创作者 (SPS 已计算)
- AI 过滤准确率: >90% (抽样 100 条人工验证)
- 随机探索比例: 实际 10-20% 有标记
- 全链路延迟: 从 L1 扫描完成到 Dashboard 可见 <4 小时
- 月成本: ≤$500

---

## 七、初版部署上线

### 部署方案 A: 阿里云全家桶 (推荐, 与百炼 LLM 同生态)

```
阿里云部署架构:
├── 轻量应用服务器 2C4G (Docker Compose 运行全部服务)
│   ├── Flask Server (:5000)
│   ├── Streamlit Dashboard (:8501)
│   ├── Cron Worker (daily_job.py)
│   └── Nginx 反向代理 (:80/:443)
├── RDS PostgreSQL 基础版 2C4G 100GB (托管数据库)
│   └── 自动备份 + 监控告警
└── 百炼 API (同账号, LLM 调用)
```

**费用明细**:

| 服务 | 规格 | 活动价 | 标准价 | 备注 |
|------|------|--------|--------|------|
| 轻量应用服务器 | 2C4G 50GB ESSD, 200Mbps | ¥199/年 (~$2.3/月) | ¥40/月 (~$5.5/月) | Docker Compose 部署全部服务 |
| RDS PostgreSQL | 基础版 2C4G 100GB | ¥228/年 (~$2.6/月) | ~¥60/月 (~$8/月) | 自动备份, 免运维; 初期也可在轻量服务器上 Docker 自建 PostgreSQL 省此费用 |
| 域名 + SSL | .com 域名 | ~¥60/年 (~$0.7/月) | - | 用于 Apify Webhook 回调 |
| 百炼 LLM API | 按量付费 | ~$5/月 | - | 已在成本预算中 |
| **合计 (活动价)** | | **~$6/月** | | 首年极低; 续费约 $15/月 |

**操作步骤**:
1. 购买轻量应用服务器, 选择 Docker 镜像 (或 Ubuntu 22.04 后手动安装 Docker)
2. 购买 RDS PostgreSQL 基础版 (或初期省钱: 在轻量服务器上 Docker 自建 PG)
3. 域名解析到轻量服务器公网 IP; 用 Certbot 申请 Let's Encrypt 免费 SSL
4. Nginx 配置: `/apify-webhook` -> Flask:5000, `/dashboard` -> Streamlit:8501
5. 安全组: 开放 80/443 (HTTP/HTTPS), 限制 5432 (PG) 仅内网访问

### 部署方案 B: 腾讯云全家桶

```
腾讯云部署架构:
├── 轻量应用服务器 2C4G 5M
├── 云数据库 PostgreSQL 基础版
└── Nginx + Docker Compose (同方案 A)
```

**费用明细**:

| 服务 | 规格 | 活动价 | 备注 |
|------|------|--------|------|
| 轻量应用服务器 | 2C4G 5M 60GB SSD | ¥188/年 (~$2.2/月) | 与阿里云同级 |
| 云数据库 PostgreSQL | 基础版 1C2G 50GB | ~¥250/年 (~$2.9/月) | 初期可 Docker 自建省此费用 |
| 域名 + SSL | .com 域名 | ~¥60/年 | - |
| **合计 (活动价)** | | **~$6/月** | 与阿里云接近 |

**腾讯云 vs 阿里云选型建议**: 阿里云优先, 因为百炼 LLM 网关在阿里云生态内, 内网调用延迟更低; 腾讯云适合已有腾讯云账号且有优惠券的团队。

### 部署方案 C: 第三方 PaaS 混合 (海外访问友好 / 快速原型)

适合需要海外节点 (Apify Webhook 回调更稳定) 或不想运维服务器的场景:

| 服务 | 推荐平台 | 费用 | 说明 |
|------|----------|------|------|
| 应用托管 (Flask+Cron) | **Zeabur** | $5/月起 | 国内团队, 支持一键部署 Flask; 腾讯云节点可选 |
| 应用托管 (备选) | **Railway** | $5/月起 | 海外节点, 自带域名, Apify Webhook 回调稳定 |
| PostgreSQL 托管 | **Supabase** Free | $0 (500MB) | 免费 500MB 足够初期; 不活跃 7 天暂停, 需 cron 保活 |
| PostgreSQL 托管 (付费) | **Supabase** Pro | $25/月 | 8GB 存储, 不暂停, 自动备份 |
| PostgreSQL 托管 (备选) | **Neon** Free | $0 (0.5GB) | Serverless, 自动 scale-to-zero; 100 CU-hours/月 |
| Streamlit 托管 | **Streamlit Community Cloud** | $0 | 免费托管 Streamlit app, 绑定 GitHub 仓库自动部署 |
| DNS + CDN + SSL | **Cloudflare** | $0 | 免费 DNS 解析 + CDN + SSL 证书, 强烈推荐 |

**混合方案示例 (最省钱)**:
- Flask Server: Zeabur $5/月
- PostgreSQL: Neon Free $0
- Streamlit: Streamlit Community Cloud $0
- DNS/SSL: Cloudflare $0
- **总计: ~$5/月** (但分散管理, 适合个人开发者原型验证)

### 推荐选择

| 场景 | 推荐方案 | 月成本 | 理由 |
|------|----------|--------|------|
| **生产环境 (首选)** | 阿里云全家桶 | ~$6-15/月 | 百炼同生态, 数据在国内, 稳定可控 |
| 已有腾讯云资源 | 腾讯云全家桶 | ~$6-15/月 | 与阿里云对等, 用已有优惠 |
| 快速原型 / 个人 | 第三方 PaaS 混合 | ~$5-10/月 | 免运维, 快速上线 |
| 海外 Webhook 优先 | Zeabur/Railway + 阿里云 RDS | ~$10-15/月 | 海外节点接收 Apify 回调更稳定 |

### docker-compose.yml 关键配置 (方案 A/B 通用)

```yaml
services:
  db:
    image: postgres:18-alpine
    volumes:
      - pgdata:/var/lib/postgresql
      - ./db/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql
    environment:
      POSTGRES_DB: craftifyx_miner
      POSTGRES_USER: miner
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    # 如果使用阿里云 RDS, 则删除此 service, 改用 RDS 连接串

  server:
    build: .
    command: gunicorn -w 2 -b 0.0.0.0:5000 server.app:app
    ports: ["5000:5000"]
    depends_on: [db]
    env_file: .env

  dashboard:
    build: .
    command: streamlit run dashboard/app.py --server.port=8501 --server.address=0.0.0.0
    ports: ["8501:8501"]
    depends_on: [db]
    env_file: .env

  cron:
    build: .
    command: python cron/daily_job.py
    depends_on: [db, server]
    env_file: .env

  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./certbot:/etc/letsencrypt
    depends_on: [server, dashboard]

volumes:
  pgdata:
```

---

## 八、成本管控配置

### 月度 $500 预算分配

| 费用项 | 月预算 | 日均 | 控制手段 |
|--------|--------|------|----------|
| Apify Starter 订阅 | $49 | - | 固定 |
| L1 Datacenter 代理 | $90 | $3 | 限制日扫描 5000 人 |
| L3 Residential 深度 | $240 | $8-12 | 仅对 AI 通过者抓取 |
| 国产大模型 API (Kimi/百炼) | $2-10 | $0.07-0.3 | Level 1/2 规则快筛覆盖 ~70% BIO 后, LLM 仅处理 ~30% 灰区; Kimi K2.5 ~$6/月; Qwen3.5-Plus ~$2/月 |
| 阿里云轻量服务器 2C4G | $3-6 | - | 活动价 ¥199/年; 标准价 ¥40/月 |
| PostgreSQL (RDS 或 Docker 自建) | $0-8 | - | RDS ¥228/年; 或轻量服务器内自建 $0 |
| 域名 + SSL (Cloudflare) | $1 | - | 域名 ¥60/年; Cloudflare 免费 SSL/CDN |
| 缓冲 | $93-122 | - | 流量波动 / 测试 / 不可预见费用 |
| **总计** | **~$390-490** | **~$13-16** | 规则快筛进一步压低 LLM 成本; 选 Qwen3.5-Plus 可压至 ~$390; 选 Kimi 约 ~$400 |

### 代码级成本控制

- `config/settings.py` 中定义 `DAILY_APIFY_BUDGET_USD=20`, `MONTHLY_LLM_BUDGET_USD=10`
- `pipeline/discovery.py` 在触发 Apify run 前检查当日累计成本，超限则跳过
- `pipeline/ai_filter.py` 记录每次调用 token 数到 `cost_tracking` 表
- Dashboard `4_cost_monitor.py` 实时展示预警

---

## 九、初版简化声明与迭代建议

### 初版可暂简化的功能

- **系统重训练**: 仅做数据回流 (Sales -> Seed 晋升)，不做 XGBoost/LogisticRegression 模型训练 -> v1.1
- **Character Consistency**: 用推文图片 URL 域名集中度替代 pHash 图像分析 -> v1.1 接入图像服务
- **圈层影响力（circle_influence_score）**: 初版即由 `creator_graph` + Seed 列表计算，无占位；若图数据缺失可暂为 0 -> v1.1 可改为按总 Seed 数比例归一化
- **Growth Score**: 无历史数据时用 0.5 占位，需运行 30 天后才有环比数据 -> 自动生效
- **Contact Probability**: 初版用 SPS * 0.8 + Monetization * 0.2 的简单公式，待 outreach 数据积累后训练模型 -> v1.2
- **反向挖掘**: 初版仅实现 Layer-1 + Layer-2，反向挖掘延后 -> v1.1
- **Apify Actor 选型**: 初版先用 1-2 个稳定 Actor 跑通，不必覆盖全部 4 类数据 -> 按需扩展

### v1.1 迭代优先级

1. 反向挖掘策略上线 (10% 预算)
2. Character Consistency pHash 计算接入
3. ~~Fan Creator Ratio~~ 已废弃；圈层影响力以 `seed_connections` 为准，可选增强：按活跃 Seed 总数动态调整归一化分母
4. Contact Probability 基于 outreach_log 训练 LogisticRegression

### v1.2 迭代

1. SPS 权重按创作者类型用 XGBoost 自动校准 (需 30+ sales_feedback)
2. 多语言 Bio Prompt 优化 (日/韩/西语), 可考虑用 Kimi 或 qwen3.5-plus 等长上下文模型处理复杂多语言 Bio
3. 相似创作者推荐 (基于 creator_features 余弦相似度)
4. 引入百炼 Batch API (50% 折扣) 处理非实时的大批量 Bio 过滤, 进一步降低成本
