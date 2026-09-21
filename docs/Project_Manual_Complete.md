# CraftifyX Miner 7.0 — 项目综合说明书

> **生成时间**: 2026-05-29
> **版本**: v7.0（基于 6.0 架构迭代）
> **文档来源**: 汇总 `README.md`、`CraftifyX-Miner-7.0-项目说明书.md`、`CraftifyX业务介绍.md`、`发现者爬取与过滤流程.md`、`LOCAL_DEVELOPMENT.md`、`OPERATIONS.md`、`db/schema.sql` 等核心文档

---

## 目录

1. [业务背景](#一业务背景)
2. [系统定位](#二系统定位)
3. [核心指标](#三核心指标)
4. [系统架构](#四系统架构)
5. [数据流程详解](#五数据流程详解)
6. [核心能力](#六核心能力)
7. [项目结构](#七项目结构)
8. [数据库设计](#八数据库设计)
9. [部署与运维](#九部署与运维)
10. [本地开发](#十本地开发)
11. [成本与ROI](#十一成本与roi)
12. [风险与应对](#十二风险与应对)
13. [附录：名词解释](#附录名词解释)

---

## 一、业务背景

**CraftifyX** 是面向全球的 **「预售验证 + 现货放量」双轮** 模式平台，将 VTuber、游戏角色、原创 OC 等虚拟 IP 变为收藏级实体商品，使中长尾创作者在**零垫资、低库存风险**下完成 IP 变现。

### 关键运营数据

| 维度 | 内容 |
|------|------|
| 创作者池 | 已合作产生销售约 **150**；签约待上线约 **170**；2026 年目标合作 **420+** |
| 近期业绩 | 近 **3 个月**净预售约 **77 万 RMB**（不含邮费），主要来自海外 VTuber/OC/游戏工作室 |
| 复购 | **90 天**复购率近 **10%**；目标通过社群提升至 **20%+** |

### 商业模式：验矿 → 采矿

- **验矿（筛选与预售验证）**：Miner 自动抓取 X/TikTok/Twitch/Discord 等信号，**50 件成团**，未成团全额退款；创作者分成短期 **25%**、规模化后 **20%**
- **采矿（现货放量）**：仅将预售数据好的款转现货；现货 SKU 上限约为预售 SKU 的 **20%**

---

## 二、系统定位

**CraftifyX Miner 7.0** 是一套端到端的「创作者发现 + 评分分层 + BD 决策 + 数据驱动进化」系统：

> 帮助 CraftifyX **每天产出约 300–500 名带 SPS 评分的海外创作者候选人**，让 BD 专注「判断」与「联系」；系统通过 **BD 反馈 + 销售数据** 双轨进化。

**一句话定位**：一套**每月约 500 美元以内**、**4 周可交付 MVP**、**越用越准**的 AI 自动化系统。

### 解决什么痛点

- BD 手动在 X 上找人，效率低、易疲劳、难量化
- 仅靠关键词搜「Artist」**漏掉大量真实创作者**（链接店铺、极简 BIO）
- 评分与「是否值得联系」缺乏统一数据语言
- **6.0 已解决「自动化发现 + 粗筛」**；**7.0 强化「少误杀、圈层可解释、可持续进化」**

---

## 三、核心指标

| 指标 | 数值 | 说明 |
|------|------|------|
| **日终局产出（深度 + 评分）** | **300–500 名创作者** | L3 深度抓取 + 10 维 + SPS 后的 BD 可见候选人规模 |
| **L1 日扫描量** | 约 **5,000** 人级 | Following 浅扫（量级随锚点数配置变化） |
| **L2 AI 过滤后** | 约 **500–800** 人/日 | 规则快筛 + LLM 后的中间池 |
| **月发现量（去重后）** | 约 **10,000–15,000** | 覆盖 VTuber / OC / 游戏开发者等；含随机探索 |
| **月度总成本** | **≤$500**（约 ¥3,500） | Apify + 国产大模型 + 服务器 + 数据库等 |
| **交付周期（MVP）** | **4 周** | 数据管道 → BIO → 评分 → Dashboard 上线 |
| **预计 BD 审核量** | ~450 人/月 | 系统按 Hub/Connector、SPS 等排序后的高优池 |
| **BIO 目标** | 综合准确率 **>90%**；误杀率持续压降 | 依赖规则 + LLM + 可选复盘库 |

---

## 四、系统架构

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

### 四层架构 + 双轨进化

| 层级 | 名称 | 要点 |
|------|------|------|
| 输入层 | 多源发现引擎 | 种子导入（100+ 销售验证创作者）、每日 Multi-hop（Layer-1/2 + 反向）、动态锚点 **60% 利用 + 40% 探索** |
| 处理层 | 智能计算引擎 | Apify **4 类**采集、**10 维指标**、轻量中心度（Hub/Connector/Peripheral）、**SPS** + **Contact Probability** |
| 应用层 | BD 决策引擎 | 分级候选池（Hub 优先 + SPS 排序）、BD Dashboard、联系执行与结果追踪 |
| 进化层 | 双轨飞轮 | Track1：BD 反馈优化联系模型；Track2：Sales/GMV 驱动 XGBoost 权重；新 Seed 晋升 |

---

## 五、数据流程详解

发现链路在 `pipeline/runner.py` 的 `run_full_pipeline()` 中按顺序执行：

```
1. 生成当日锚点
   → 2. L1：Following 浅层爬取（Apify）
      → 3. 入库
         → 4. 规则 + AI 过滤
            → 5. 发现来源打标
               → 6. 深度抓取（推文+画像）
                  → 7. 特征计算
                     → 8. SPS 评分
```

### 5.1 每日锚点生成

**配置**：`DAILY_ANCHOR_COUNT=20`，`EXPLORATION_RATIO=0.20`

| 锚点类型 | 比例 | 规则 |
|----------|------|------|
| **常规锚点** | 80% | 从 `is_seed = true` 且 `seed_tier IN ('S', 'A')` 中选取；不足补 `B` 级 |
| **探索锚点** | 20% | 轮询 `geo_explore` → `hashtag_explore` → `time_explore` |

探索标签示例：`#絵描きさんと繋がりたい`、`#VTuber`、`#indiegame`、`#ArtistOnTwitter`

### 5.2 L1 Following 爬取

- **预算门禁**：当日 `apify_cost_usd ≥ DAILY_APIFY_BUDGET_USD`（默认 $20）则不启动
- **Actor**：`apidojo/twitter-user-scraper`，`getFollowing: true`
- **每条锚点最多拉取**：`MAX_FOLLOWING_PER_ANCHOR`（默认 500）
- **以 `#` 开头的探索锚点不会进入 Following 请求**

### 5.3 入库规则

- `INSERT ... ON CONFLICT (platform, platform_account_id) DO UPDATE`
- `bio` / `website`：**仅当新值非空** 才覆盖
- `followers` / `following` / `tweets_count`：用新值覆盖
- 新插入行默认 `bd_status = 'pending'`

### 5.4 过滤管道（三级）

**仅处理 `bd_status = 'pending'` 且 `bio` 非空的用户。**

| 级别 | 名称 | 判定逻辑 |
|------|------|----------|
| **Level 1** | 硬规则 / Link DNA | 作品集与店铺链接命中 → `rule_passed`（高置信，可跳过 LLM） |
| **Level 2** | 语义矩阵 | 身份词、动作+工具词组合、Emoji 信号命中 → `rule_passed`；误杀防范命中 → `rule_rejected` |
| **Level 3** | LLM 兜底 | 灰区 BIO 批量调用国产大模型；YES → `ai_passed`，NO → `ai_rejected` |

**类型分类**：按 `bio_rules.yaml` 的 `type_classification` 首条匹配；否则默认 `content_creator`。

### 5.5 深度抓取

- **入选条件**：`bd_status IN ('rule_passed', 'ai_passed')` 且**尚无 tweets 记录**
- **批量大小**：`DEEP_SCRAPE_BATCH_SIZE`（默认 50）
- **Actor**：`apidojo/tweet-scraper`（Residential Proxy）
- 回写 `creators` + `tweets`，更新 `discovery_batches.after_deep_scrape`

### 5.6 特征与 SPS

- **特征**：对所有**已有推文、尚无 `creator_features`** 的创作者计算 10 维特征
- **SPS**：对所有**已有特征、尚无 `creator_scores`** 的创作者打分

---

## 六、核心能力

### 能力 1：三层发现引擎

- **Layer-1**：常规扩展 — 从动态锚点抓取 Following（约 **60%** 预算）
- **Layer-2**：超级连接器 — 被多个 Seed 共同关注的账号再扩展（约 **30%**）
- **反向挖掘**：高价值 Seed 的粉丝中筛创作者（约 **10%**）
- **随机探索**：预留 **10–20%** 用于跨地域 / 跨品类

### 能力 2：BIO 智能筛选（四级产品叙事）

| 级别 | 含义 | 说明 |
|------|------|------|
| **Level A** | 硬规则 / Link DNA | 作品集与店铺链接命中；高置信「创作者」信号 |
| **Level B** | 语义矩阵 | 身份 / 动作 / 工具词等；与 `bio_rules.yaml` 一致 |
| **Level C** | LLM | 灰区 BIO、「宁漏勿错」策略；批量 JSON 输出 |
| **Level D** | 误杀复盘（可选） | BD 标记「系统漏掉但高价值」的 BIO；Few-shot / 周更 Prompt |

### 能力 3：数据化评分 + 轻量中心度

**10 维指标**：

| 维度 | 含义 | 计算要点 |
|------|------|----------|
| Audience | 规模 | `log10(followers+1)×20` |
| Engagement | 粘性 | `(赞+转×2+评×3)/followers×100` |
| Virality | 爆款 | top3 均值 / 月均值，>5x → 100 |
| Posting | 勤勉 | 月发帖数/30×100 |
| Monetization | 变现 | Bio 关键词：商店 90 / 接单 60 / 无 0 |
| Growth | 增速 | 月环比粉丝增长 |
| Audience Segment | 受众细分 | Bio / Website / Username 语义分类 |
| Character Consistency | IP 化 | pHash 最大聚类/总图片×100 |
| Community | 社区 | `(mentions×2+fanart×5)` 标准化 |
| Community Score | 社群 | 互动密度标准化 |

**中心度分层**（基于被 Seed 关注数）：

- **Hub**：被 **≥5** 个 Seed 关注 — BD 最优先
- **Connector**：**2–4** 个 — 次级优先
- **Peripheral**：**0–1** 个 — 依赖 SPS

### 能力 4：双轨进化

- **Track 1**：BD 触达与回复结果 → 优化排序与 **Contact Probability**
- **Track 2**：`sales_feedback`（GMV 等）→ **SPS 权重校准**、**高 GMV 晋升 Seed**（如 GMV > $1000）

### 能力 5：BD 工作台

- 日报、候选人卡片（**10 维雷达 + 中心度 + SPS**）
- Interested / Rejected / Deferred
- 联系与销售录入、成本面板
- 可选「标记误杀」入口

---

## 七、项目结构

```
craftifyxminer/
├── config/                     # 配置文件
│   ├── settings.py             # 环境变量与全局配置
│   ├── apify_config.yaml       # Apify Actor 参数
│   ├── weights.yaml            # 5 类创作者 SPS 权重矩阵
│   └── bio_rules.yaml          # BIO 知识库
├── auth/                       # 认证与权限 (bcrypt / JWT / Session)
├── db/                         # 数据库 (连接池 / schema / 索引 / 迁移)
├── server/                     # Flask 后端 (Webhook / API / 健康检查)
├── pipeline/                   # 数据管道
│   ├── seed_import.py          # 种子导入
│   ├── discovery.py            # 每日发现引擎
│   ├── bio_rule_filter.py      # Level 1/2 规则快筛
│   ├── ai_filter.py            # Level 3 LLM 批量过滤
│   ├── deep_scrape.py          # 深度抓取触发
│   ├── feature_engine.py       # 10 维指标计算
│   ├── sps_scorer.py           # SPS 评分 + 中心度分层
│   └── evolution.py            # 飞轮进化
├── dashboard/                  # Streamlit BD 工作台
│   ├── pages/
│   │   ├── 1_daily_report.py   # 每日发现报告
│   │   ├── 2_candidates.py     # 候选人浏览与 BD 判定
│   │   ├── 3_outreach.py       # 联系追踪与销售反馈
│   │   ├── 4_cost_monitor.py   # 成本监控面板
│   │   └── 5_admin.py          # Admin 管理面板
│   └── components/
│       └── radar_chart.py      # 10 维雷达图
├── nginx/                      # Nginx 反向代理配置
├── scripts/                    # 运维脚本 (deploy / backup)
├── cron/                       # APScheduler 定时任务
├── tests/                      # pytest 用例
├── docs/                       # 项目文档
├── .env.example                # 环境变量模板
├── requirements.txt            # Python 依赖
├── Dockerfile                  # 非 root 用户镜像
├── docker-compose.yml          # 本地开发
└── docker-compose.prod.yml     # 生产部署
```

---

## 八、数据库设计

### 核心表结构

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `creators` | 创作者主档案 | `username`, `bio`, `followers`, `bd_status`, `is_seed`, `creator_type_auto`, `discovered_date` |
| `tweets` | 推文数据 | `tweet_id`, `creator_id`, `likes`, `retweets`, `replies`, `views`, `text`, `media_urls` |
| `creator_features` | 8 维特征指标 | `audience_score`, `engagement_score`, `virality_score`, `growth_score`, `posting_score`, `monetization_score`, `character_consistency`, `community_score`, `audience_segment_score` |
| `creator_graph` | 关系图谱 | `creator_id`, `connected_creator_id`, `connection_type` |
| `creator_scores` | SPS 评分 + 中心度 | `sps_score`, `sellability_score`, `is_sellable`, `centrality_tier`, `seed_connections`, `contact_probability` |
| `sales_feedback` | 销售反馈（进化核心）| `gmv`, `units_sold`, `launch_date`, `conversion_rate` |
| `outreach_log` | BD 联系追踪 | `contact_channel`, `response_received`, `deal_status` |
| `cost_tracking` | 成本监控 | `apify_cost_usd`, `llm_cost_usd`, `proxy_cost_usd`, `total_cost_usd` |
| `discovery_batches` | 发现批次追踪 | `batch_date`, `anchor_seeds`, `raw_discovered`, `after_ai_filter`, `after_deep_scrape` |
| `users` | 登录与权限 | `username`, `role`, `is_active` |
| `login_attempts` | 登录审计 | `ip_address`, `success`, `attempted_at` |
| `model_evaluations` | 模型评估 | `recall`, `precision_score`, `f2_score`, `spearman_corr` |
| `bd_decisions` | BD 多用户决策 | `decision`, `note`, `creator_id`, `user_id` |

### 规模预估

- `creators`: ~5 万
- `tweets`: ~250 万
- `creator_graph`: ~50 万边
- `sales_feedback`: ~1000/年

---

## 九、部署与运维

### 9.1 生产架构

```
┌─────────┐     ┌──────────────┐     ┌──────────────┐
│  nginx   │────>│  server      │     │  dashboard   │
│  :80     │     │  (gunicorn)  │     │  (streamlit) │
└─────────┘     │  :5000       │     │  :8501       │
                └──────────────┘     └──────────────┘
                        │                    │
                        └────────┬───────────┘
                                 │
                        ┌────────▼────────┐
                        │   PostgreSQL     │
                        │   (阿里云 RDS)   │
                        └─────────────────┘
                                 │
                        ┌────────▼────────┐
                        │      cron       │
                        │  (APScheduler)  │
                        └─────────────────┘
```

### 9.2 定时任务

| 时间 (Asia/Shanghai) | Job ID | 执行内容 |
|---------------------|--------|---------|
| **08:00** | `daily_pipeline` | 全链路：锚点 → L1 扫描 → 深度抓取 → 特征 → SPS |
| **23:00** | `daily_summary` | 日报统计 + 成本核算 + 种子晋升 |

### 9.3 一键部署

```bash
sudo bash scripts/deploy.sh
```

自动完成：安装 Docker、配置 `.env`、初始化数据库、创建 Admin、启动 Nginx + Flask + Streamlit + Cron、配置每日备份。

### 9.4 常用运维命令

```bash
# 查看容器状态
docker compose -f docker-compose.prod.yml ps

# 查看日志
docker compose -f docker-compose.prod.yml logs -f

# 手动备份
bash scripts/backup_db.sh

# 用户管理
docker compose -f docker-compose.prod.yml run --rm server python -m auth.manage create-user --username bd1
```

### 9.5 常见排障

| 症状 | 排查 |
|------|------|
| LLM 反复重试 / 401 | `git pull && docker compose up -d --build`；检查 `.env` 中各 `*_API_KEY` |
| JSON 解析失败 | `.env` 中设 `LLM_MAX_TOKENS=16384` |
| `.env` 改了没生效 | `docker compose up -d --force-recreate`（restart 不会重读 `.env`） |
| Apify 预算用完 | 当日不再触发；次日自动恢复；或临时提额 `DAILY_APIFY_BUDGET_USD` |

---

## 十、本地开发

### 10.1 环境要求

- Python 3.11+
- PostgreSQL 18+（或使用 Docker）
- Apify 账号 + 国产大模型 API Key

### 10.2 快速启动

```bash
# 1. 配置环境
cp .env.example .env

# 2. 安装依赖
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. 启动数据库
docker compose up -d db

# 4. 跑测试
pytest tests/ -v

# 5. 启动服务
python -m server.app              # Flask :5000
streamlit run dashboard/app.py    # Dashboard :8501
```

### 10.3 种子导入

```bash
python -m pipeline.seed_import --csv data/sample_seeds.csv
```

Tier 规则：`S` > 2000，`A` > 500，`B` > 100，其余为 `C`。

### 10.4 批量补算特征与 SPS

```bash
python scripts/backfill_features_sps.py --max-rounds 5
```

---

## 十一、成本与 ROI

### 月度成本预算

| 费用项 | 预算 |
|--------|------|
| Apify 订阅 + 代理 | ~$380 |
| 国产大模型 API | ~$2–20 |
| 云服务器 (阿里云 2C4G) | ~$3–15 |
| 数据库 | ~$0–8 |
| 缓冲 | ~$90–110 |
| **合计** | **≤$500/月** |

### 产出与 ROI（文档口径）

- **月发现量**：约 **15,000**（500 人/日 × 30）
- **预计成交**：**15–30** 人（10–20% 转化假设）
- **月度 GMV 增量**：**$75K–$150K**
- **系统成本占 GMV**：约 **0.5%**

### 技术选型

| 组件 | 技术选型 |
|------|---------|
| 后端 | Python (Flask) |
| 数据采集 | Apify (Twitter/X Actor) |
| AI 过滤 | 国产大模型 (Qwen / Kimi / DeepSeek，OpenAI 兼容接口) |
| 数据库 | PostgreSQL 18+ |
| Dashboard | Streamlit + Plotly |
| 定时任务 | APScheduler |
| 部署 | Docker Compose + Nginx |

---

## 十二、风险与应对

| 风险 | 应对 |
|------|------|
| Apify 限流 / 成本波动 | 分层代理、日预算上限、队列削峰 |
| BIO 漏判 | 规则库迭代 + LLM Prompt + 可选误杀库 |
| 圈层数据稀疏 | 新候选人 `seed_connections=0` 为常态，依赖 SPS 与其它维；随图扩大逐步显现 |

---

## 附录：名词解释

| 术语 | 含义 |
|------|------|
| **Seed** | 已验证或高潜创作者；系统从其关系网扩展发现 |
| **SPS** | Seed Potential Score，10 维加权综合分（0–100） |
| **Sellability** | 可销售性评分（0–100），独立模型判断「是否建议联系」 |
| **Hub / Connector / Peripheral** | 被 Seed 关注数分层；Hub ≥5, Connector 2–4, Peripheral 0–1 |
| **passed** | `bd_status IN ('rule_passed', 'ai_passed')`，即通过过滤的候选人 |
| **三级管道** | L1 浅扫 → L2 BIO 过滤 → L3 深度抓取 |
| **四级叙事** | Level A 硬规则 → Level B 语义矩阵 → Level C LLM → Level D 误杀复盘 |

---

*本文档由项目核心文档汇总生成。若与代码不一致，以仓库 `db/schema.sql`、`config/` 及实际代码为准。*
