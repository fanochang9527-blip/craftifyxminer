# CraftifyX Miner — SPS ML 模型重构方案（完整版）

> **概述**：将 SPS 评分从人工权重加权求和改为 ML 模型（线性回归 / XGBoost）训练预测，种子作为正样本，以 10 维特征预测 total_sales；同时重构每日流水线为「全量种子关注爬取 + 30 天去重 + ML 预测评分」，优化 bio 规则、BD 工作台、特征计算和模型监控。

---

## 目录

- [一、废弃 seed_tier](#一废弃-seed_tier)
- [二、Bio 规则升级](#二bio-规则升级)
- [三、种子导入必须包含 creator_type](#三种子导入必须包含-creator_type)
- [四、种子导入后自动触发 deep scrape + 特征计算 + 模型训练](#四种子导入后自动触发-deep-scrape--特征计算--模型训练)
- [五、10 维特征计算优化](#五10-维特征计算优化)
- [六、创作者类型自动分类器](#六创作者类型自动分类器)
- [七、ML 模型设计](#七ml-模型设计)
- [八、改写 SPS 评分逻辑](#八改写-sps-评分逻辑)
- [九、模型指标监控](#九模型指标监控)
- [十、BD 审核工作台重构](#十bd-审核工作台重构)
- [十一、重构每日流水线](#十一重构每日流水线)
- [十二、配置与 DB Migration](#十二配置与-db-migration)
- [附录 A：任务清单](#附录-a任务清单)
- [附录 B：关键决策说明](#附录-b关键决策说明)

---

## 一、废弃 seed_tier

`seed_tier` 字段在以下文件中被使用，需全部移除或改写：

- `pipeline/seed_import.py` — 删除 `classify_tier()` 函数及 `TIER_THRESHOLDS`；导入时不再写 `seed_tier`
- `pipeline/discovery.py` L52 — `seed_tier IN ('S','A')` 改为只按 `is_seed = true` 选取
- `pipeline/evolution.py` L36 — 移除 `seed_tier = 'C'`；`monthly_report()` L61-72 不再按 tier 分组，改为按 creator_type 分组
- `dashboard/pages/3_outreach.py` L119 — 移除 `seed_tier = 'C'`
- **DB migration**: `ALTER TABLE creators DROP COLUMN seed_tier;`

---

## 二、Bio 规则升级

### 2.1 用新 JSON 知识库覆盖 `config/bio_rules.yaml`

将最新 JSON 规则（基于 102 名种子用户生成）转为 YAML 格式，主要增补：

- `link_dna` → 保持现有分 high/medium 两级，增加 `instagram.com`
- `type_tags` 从 4 类扩展为 **6 类**：
  - OC_Creator / VTuber / Fan_Second_Creation / Game_Studio / Virtual_IP / Plush_Merch
- `weak_signals` 补充：`work email`, `business inquiry`, `limited`, `drop`, `my shop`, `preorder open`
- `emojis` 补充 `plush` 组（🧸🐻🔨🛠️）和 `engagement` 组（❤️💕🔥💥）
- `keywords.tools` 补充：`saipaint`, `unity`, `unreal`, `toys`
- `keywords.identity` 补充：`OC creator`, `indie artist`, `original character`, `plush artist`, `doll maker` 等
- `rules` 新增 `studio_flag`：出现 team/studio/we 而非 I/my 时倾向判定为工作室
- `confidence_threshold` 新增 high=0.95 / medium=0.75 显式配置

### 2.2 `bio_rule_filter.py` 适配

- `_classify_type()` 方法扩展，对齐新的 6 类 type_tags
- 创作者最终归为 6 种类型（含 unknown），中间 type_tags 的映射关系：
  - `Plush_Merch` → `oc_creator`
  - `Virtual_IP` → `vtuber`
  - `Fan_Second_Creation` → `fan_artist`
  - `Game_Studio` → `game_creator`
  - 无匹配 → `unknown`
- 多类型命中时，选匹配信号数最多的类型

### 2.3 种子导入时自动更新 bio 规则

在 `seed_import.py` 导入流程中，对新种子的 bio 做规则匹配。若发现新种子的 bio 中存在关键词/链接不在现有规则中，半自动处理：生成 diff 建议文件 `config/bio_rules_suggestions.yaml`，供人工审核后合并。

---

## 三、种子导入必须包含 creator_type

### 3.1 CSV 格式要求

`seed_import.py` 导入时，CSV 必须包含 `creator_type` 列，值为以下六种之一：

- `oc_creator` / `vtuber` / `fan_artist` / `game_creator` / `content_creator` / `unknown`
- 缺失或不合法则报错拒绝导入
- 种子允许标注为 `unknown`（暂时无法确定类型时使用）

### 3.2 DB 变更 — 双字段设计

`creators` 表新增两个类型字段，分别存放人工标注和机器分类结果：

| 字段 | 类型 | 说明 |
|------|------|------|
| `creator_type_manual` | VARCHAR(20) | 人工标注类型（种子导入时由 CSV 提供，BD 审核时可修正） |
| `creator_type_auto` | VARCHAR(20) | 机器自动分类结果（由 `type_classifier.py` 生成） |

使用规则：

- 业务逻辑中统一使用 `COALESCE(creator_type_manual, creator_type_auto, 'unknown')` 取有效类型，**人工标注优先**
- 两字段并存、互不覆盖，方便后续对比分析自动分类器的准确率
- 原 `creator_scores.creator_type` 字段可废弃或保持同步

---

## 四、种子导入后自动触发 deep scrape + 特征计算 + 模型训练

在 `seed_import.py` 的 `import_seeds()` 末尾追加链式调用：

1. 对所有新导入种子调用 deep scrape（**不受预算限制**），拉取推文
2. 调用 `compute_features_for_creator()` 计算 10 维特征
3. 调用 `sps_model.train_model()` 重训练 ML 模型

```
seed CSV → 入库 creators（写入 creator_type_manual）
  → deep scrape (Apify) → tweets 入库
  → 自动分类器 → 写入 creator_type_auto（便于与人工标注对比）
  → 计算 10 维特征 → creator_features 入库
  → 重训练 ML 模型 → models/sps_model.joblib
```

---

## 五、10 维特征计算优化

改动文件：`pipeline/feature_engine.py`

| # | 维度 | 当前实现 | 优化方向 | 阶段 |
|---|------|---------|---------|------|
| 1 | audience_score | `log10(followers+1)*20` | 加去水校正：`estimated_real = followers * (1 - bot_ratio)`，bot_ratio 由 engagement/follower 比值估算 | v1 |
| 2 | engagement_score | 简单均值 | 加时间衰减：近 7 天权重 1.0，8-14 天 0.7，15-30 天 0.4 | v1 |
| 3 | virality_score | top3/monthly 比值 | 保持，逻辑合理 | — |
| 4 | posting_score | 推文数/30 | 保持，改为取近 30 天实际日期范围内的推文数 | v1 |
| 5 | monetization_score | bio 关键词硬编码 | 改用升级后的 bio_rules.yaml（link_dna + action_keywords），更全面 | v1 |
| 6 | growth_score | 固定 50.0 占位 | **v1 仍为占位**（需要定期快照粉丝数才能算月环比，待 v2） | v2 |
| 7 | circle_influence_score | seed_connections * 20 | 改名为 `fan_creator_ratio`：抽样粉丝中创作者占比。**v1 仍用 seed_connections 近似** | v2 |
| 8 | character_consistency | 图片域名集中度 | **v1 保持现有**（pHash 图像聚类需要下载图片 + imagehash 库，待 v2） | v2 |
| 9 | community_score | mentions + fanart 关键词计数 | 增加 fanart 被转发数的加权 | v1 |
| 10 | data_confidence | 账龄 + 资料完整度 | 保持，逻辑合理 | — |

**v1 可立即实施**：#1 去水校正、#2 时间衰减、#5 对接 bio_rules、#9 fanart 转发加权

**v2 待基础设施**：#6 月环比（需快照）、#7 粉丝抽样（需 API）、#8 pHash（需图片下载）

---

## 六、创作者类型自动分类器

新建 `pipeline/type_classifier.py`：

```python
def classify_creator_type(bio: str, website: str, tweets: list[dict]) -> str:
    """基于 bio_rules.yaml 的 type_tags + 推文内容，返回六种类型之一。

    六种类型：oc_creator / vtuber / fan_artist / game_creator / content_creator / unknown
    优先级：type_tags 精确匹配 > 推文内容关键词 > 无匹配则返回 'unknown'
    多类型命中时，选匹配信号数最多的类型。
    """
```

分类流程：

- **种子导入时**：CSV 中的 `creator_type` 写入 `creator_type_manual`；同时跑一次分类器写入 `creator_type_auto`，便于对比人工与机器判断
- **新爬取创作者**：deep scrape 后调用分类器，结果写入 `creator_type_auto`；`creator_type_manual` 为空，等待 BD 审核
- **BD 工作台**：BD 标注的类型写入 `creator_type_manual`，不覆盖 `creator_type_auto`，两字段并存
- **业务使用**：`COALESCE(creator_type_manual, creator_type_auto, 'unknown')`，人工标注优先
- **对比分析**：可随时统计 `creator_type_manual != creator_type_auto` 的比例，识别分类器薄弱类型
- **唯一类型约束**：每个创作者的有效类型只有一个

---

## 七、ML 模型设计

### 7.1 为什么用 1 个模型而非 5 个

- 当前种子约 102 个，平均每类仅约 20 个，**样本太少无法支撑 5 个独立模型**
- XGBoost 的树分裂天然能学到「对 OC 创作者，character_consistency 更重要」这类交互效应
- 1 个模型维护成本低，训练/部署简单
- **未来演进**：每类样本 >= 100 时可考虑拆分为 per-type 模型

### 7.2 模型设计

- **输入特征**：10 维数值特征 + `creator_type` one-hot 编码（6 列，含 unknown）= **16 维**
- **目标**：`total_sales`
- **模型选择**：
  - 样本 < 30：Ridge 回归（L2 正则化线性模型，小样本稳定）
  - 样本 >= 30：XGBoost 回归
- **SPS 输出**：模型预测的 total_sales，再 MinMax 归一化到 0-100

### 7.3 核心 API — `pipeline/sps_model.py`

```python
def train_model() -> dict:
    """从 DB 取种子特征+销售额+类型，训练模型。
    返回 {model_type, n_samples, r2, mae, spearman, f2_score}。"""

def load_model():
    """加载已训练模型（如无返回 None）。"""

def predict_sps(features: dict, creator_type: str) -> float:
    """预测 SPS（0-100）。"""
```

模型持久化：

- 模型文件：`models/sps_model.joblib`
- 元数据：`models/sps_model_meta.json`（训练时间、样本数、R2、MAE、Spearman）

### 7.4 新增依赖

`requirements.txt` 追加：`scikit-learn`, `xgboost`

---

## 八、改写 SPS 评分逻辑

改动文件：`pipeline/sps_scorer.py`

- `calc_sps(features, creator_type)` 改为调用 `sps_model.predict_sps(features, creator_type)`
- 模型未训练时，使用当前加权求和作为 fallback（`config/weights.yaml` 保留）
- `contact_probability` 公式保持不变（SPS*0.8 + monetization*0.2）
- `centrality` 分层保持不变

---

## 九、模型指标监控

### 9.1 指标体系

#### 分类/排序指标（核心）

| 指标 | 定义 | 目标 |
|------|------|------|
| **Recall** | 正样本中被模型预测为正的比例 | **>= 90%** |
| **Precision** | 预测正样本中确实被 BD 认可的比例 | **>= 50%** |
| **F2-Score** | 偏向 Recall 的综合指标：`5 * P * R / (4P + R)` | 与 recall 目标一致 |
| **Precision@250** | 每日推给 BD 的 top 250 中被标记「感兴趣」的比例 | 直接对应 BD 日处理量 |
| **Spearman 相关系数** | SPS 排名与 total_sales 排名的单调相关性 | 衡量排序能力 |

其中：
- **正样本** = BD 标记为「感兴趣」或有成交记录的创作者
- **预测正样本** = SPS >= 阈值（阈值可调，初始取中位数）

#### 回归指标（训练时评估）

| 指标 | 定义 |
|------|------|
| **R²** | 模型解释了多少比例的 total_sales 方差 |
| **MAE** | 平均绝对误差 |

### 9.2 实现

新建 DB 表 `model_evaluations`：

```sql
CREATE TABLE model_evaluations (
    id SERIAL PRIMARY KEY,
    evaluated_at TIMESTAMP DEFAULT NOW(),
    model_version TEXT,
    n_seeds INTEGER,
    n_predictions INTEGER,
    n_bd_reviewed INTEGER,
    n_interested INTEGER,
    n_rejected INTEGER,
    recall FLOAT,
    precision_score FLOAT,
    f2_score FLOAT,
    precision_at_250 FLOAT,
    spearman_corr FLOAT,
    r2 FLOAT,
    mae FLOAT,
    sps_threshold FLOAT,
    notes TEXT
);
```

新建 `pipeline/model_monitor.py`：

- `evaluate_model()`：查询所有有 BD 反馈的创作者，计算 Recall / Precision / F2-Score / Precision@250 / Spearman 相关系数
- 在每日流水线末尾自动执行，结果写入 `model_evaluations` 表
- 若 Recall 低于 90% 或 Precision@250 低于 50%，在 summary 中给出 warning

### 9.3 Dashboard 展示

在 daily report 页面新增模型健康度卡片：Recall / Precision / F2-Score / Precision@250 / Spearman / 训练样本数 / 上次训练时间。

---

## 十、BD 审核工作台重构

改动文件：`dashboard/pages/2_candidates.py` + `dashboard/candidates_query.py`

### 10.1 创作者类型标注

每行增加「创作者类型」下拉框，选项（六种）：

- `oc_creator` / `vtuber` / `fan_artist` / `game_creator` / `content_creator` / `unknown`

BD 选择后写入 `creators.creator_type_manual`，**不覆盖** `creator_type_auto`（机器分类结果保留）。两个字段并存，方便后续对比分析分类器准确率。`unknown` 用于 BD 无法确定类型的情况，便于统计分类器盲区。

### 10.2 操作简化

将当前 4 个按钮简化为 **2 个**：

- **感兴趣**：`bd_decision = 'interested'`，创作者进入创作者池
- **拒绝**：`bd_decision = 'rejected'`

移除 flagged / deferred 状态。

### 10.3 创作者池（感兴趣列表）

改造 `dashboard/pages/3_outreach.py` 的 pending contact 区域为「创作者池」，展示字段：

| 字段 | 来源 |
|------|------|
| 客户编号 | `creators.id` |
| 创作者类型 | `COALESCE(creators.creator_type_manual, creators.creator_type_auto, 'unknown')` |
| 创作者 ID | `creators.username` |
| 主页地址 | `https://x.com/{username}` |
| 粉丝数 | `creators.followers` |
| SPS 分 | `creator_scores.sps_score` |
| BD 账号 | `creators.bd_assigned_to`（BD 审核时自动记录当前登录用户） |
| 进入时间 | `creators.last_bd_update`（标记感兴趣的时间） |

---

## 十一、重构每日流水线

### 11.1 锚点生成 — `pipeline/discovery.py`

- `generate_daily_seeds()` 改为选取 **所有 `is_seed = true` 的种子**
- 移除 `DAILY_ANCHOR_COUNT`、`EXPLORATION_RATIO`、explore 锚点逻辑

### 11.2 L1 Scan

- `trigger_l1_scan()` 移除预算检查，全量种子一次性传给 Apify Following Actor

### 11.3 30 天去重

`deep_scrape.py` 的 `_get_pending_candidates()` 加入：

```sql
AND NOT EXISTS (
    SELECT 1 FROM tweets t
    WHERE t.creator_id = c.id AND t.collected_at > NOW() - INTERVAL '30 days'
)
```

### 11.4 Deep scrape

- `_check_budget()` 改为仅 warning 不阻断

### 11.5 Runner — `pipeline/runner.py`

流水线步骤调整为 **7 步**：

```
1. Generate anchors     — 全量种子
2. L1 scan              — 爬取种子关注的用户
3. Deep scrape          — 过滤后的候选人，30 天去重
4. Type classification  — 对新爬取创作者自动分类（写入 creator_type_auto）
5. Feature computation  — 10 维特征计算
6. ML SPS prediction    — 模型预测评分
7. Model evaluation     — 基于 BD 反馈计算 Recall/Precision/F2/P@250/Spearman
```

---

## 十二、配置与 DB Migration

### 12.1 配置变更 — `config/settings.py`

- 废弃：`DAILY_ANCHOR_COUNT`, `EXPLORATION_RATIO`
- `DAILY_APIFY_BUDGET_USD` 改为仅监控用途，不阻断流水线
- 新增：`MODEL_PATH = PROJECT_ROOT / "models" / "sps_model.joblib"`
- 新增：`MODEL_META_PATH = PROJECT_ROOT / "models" / "sps_model_meta.json"`

### 12.2 DB Migration — `db/migrations/004_sps_ml_refactor.sql`

```sql
-- 废弃 seed_tier
ALTER TABLE creators DROP COLUMN IF EXISTS seed_tier;

-- 创作者类型：人工标注 + 机器分类，双字段并存
ALTER TABLE creators ADD COLUMN IF NOT EXISTS creator_type_manual VARCHAR(20);
ALTER TABLE creators ADD COLUMN IF NOT EXISTS creator_type_auto VARCHAR(20);

-- 模型评估表
CREATE TABLE IF NOT EXISTS model_evaluations (
    id SERIAL PRIMARY KEY,
    evaluated_at TIMESTAMP DEFAULT NOW(),
    model_version TEXT,
    n_seeds INTEGER,
    n_predictions INTEGER,
    n_bd_reviewed INTEGER,
    n_interested INTEGER,
    n_rejected INTEGER,
    recall FLOAT,
    precision_score FLOAT,
    f2_score FLOAT,
    precision_at_250 FLOAT,
    spearman_corr FLOAT,
    r2 FLOAT,
    mae FLOAT,
    sps_threshold FLOAT,
    notes TEXT
);
```

---

## 附录 A：任务清单

| # | 任务 ID | 描述 |
|---|---------|------|
| 1 | drop-seed-tier | 废弃 seed_tier：移除 seed_import.py 的 classify_tier、discovery.py 的 tier 过滤、evolution.py 的 tier 逻辑、dashboard 引用；新建 DB migration |
| 2 | bio-rules-upgrade | 用新 JSON 规则覆盖 bio_rules.yaml（补充 type_tags/weak_signals/emojis）；bio_rule_filter.py 适配新格式；seed_import 时半自动更新 bio 规则 |
| 3 | seed-import-type | seed_import.py 要求 CSV 必须包含 creator_type 字段（六种之一，含 unknown），写入 creators.creator_type_manual |
| 4 | seed-deep-scrape | seed_import.py 导入后自动触发 deep scrape + 自动分类 + 特征计算 + 模型重训练（不受预算限制） |
| 5 | feature-engine-v2 | 优化 10 维特征计算 v1 部分：audience 去水校正、engagement 时间衰减、monetization 对接 bio_rules、community fanart 转发加权 |
| 6 | creator-type-classifier | 新建 pipeline/type_classifier.py：基于 bio 规则 + type_tags 对新爬取创作者自动分类（六种类型，含 unknown），结果写入 creator_type_auto |
| 7 | ml-model-module | 新建 pipeline/sps_model.py：1 个统一模型（creator_type one-hot 6 列），Ridge/XGBoost 训练、保存、加载、预测 |
| 8 | rewrite-sps-scorer | 改写 sps_scorer.py 的 calc_sps() 为 ML 模型预测，保留 weighted-sum 作为 fallback |
| 9 | model-metrics-tracking | 新建 model_evaluations 表 + pipeline/model_monitor.py：基于 BD 反馈自动计算 Recall/Precision/F2/Precision@250/Spearman |
| 10 | bd-workbench-revamp | 重构 2_candidates.py：加创作者类型标注（六种，写入 creator_type_manual）；操作简化为感兴趣/拒绝 |
| 11 | creator-pool-page | 新建或扩展 3_outreach.py 创作者池视图：客户编号、类型、ID、主页、粉丝、SPS、BD、进入时间 |
| 12 | pipeline-all-seeds | discovery.py 改为选取全量种子、移除 DAILY_ANCHOR_COUNT/EXPLORATION_RATIO/explore 逻辑 |
| 13 | remove-budget-block | discovery.py 和 deep_scrape.py 移除预算阻断，改为仅 warning |
| 14 | 30day-dedup | deep_scrape.py 候选筛选加入 30 天去重 |
| 15 | update-runner | runner.py 流水线步骤对齐新逻辑（7 步：含类型分类 + 模型评估） |
| 16 | config-and-migration | settings.py 清理配置；DB migration：drop seed_tier、加 creator_type_manual/auto 双字段、新建 model_evaluations 表 |

---

## 附录 B：关键决策说明

### B.1 为什么用 1 个模型而非 5 个

- 当前种子约 102 个，平均每类仅约 20 个，**样本太少无法支撑 5 个独立模型**
- XGBoost 的树分裂天然能学到类型与特征维度的交互效应
- 1 个模型维护成本低，一次训练、一次部署
- 演进路线：每类样本 >= 100 时再考虑拆分为 per-type 模型

### B.2 10 维特征 v1 / v2 分期

- **v1（本次实施）**：audience 去水校正、engagement 时间衰减、monetization 对接 bio_rules、community fanart 转发加权
- **v2（需额外基础设施）**：growth 月环比（需定期快照粉丝数）、fan_creator_ratio 粉丝抽样（需额外 API 调用）、character_consistency pHash（需下载图片 + imagehash 库）

### B.3 Bio 规则更新策略

- 全自动追加到 YAML 风险较高（可能引入噪声）
- 采用半自动方案：自动生成建议文件 `config/bio_rules_suggestions.yaml`，人工审核后合并

### B.4 creator_type 双字段设计

- `creator_type_manual`（人工标注）和 `creator_type_auto`（机器分类）独立存储、互不覆盖
- 业务逻辑用 `COALESCE(manual, auto, 'unknown')` 取有效类型，人工优先
- 可随时统计 `manual != auto` 的比例，量化分类器准确率，持续优化规则
- BD 在工作台标注 unknown 类型，可反向识别分类器的盲区

### B.5 模型评估指标选择

- **Recall >= 90%**（查全）：确保好的创作者不被遗漏，BD 能看到绝大多数潜力创作者
- **Precision >= 50%**（查准）：BD 每审核 2 个候选人，至少 1 个值得跟进，保证工作效率
- **F2-Score**：综合指标偏向 Recall，与查全优先的业务目标一致
- **Precision@250**：直接对应 BD 每日处理量，最具业务指导意义
- **Spearman 相关系数**：衡量排序能力——BD 关心的本质是「SPS 高的创作者是否真的销售好」，而非精确金额预测
