# CraftifyX Miner 6.0 — 本地文档

**在线原文**：[https://hlso6imk735ho.ok.kimi.link](https://hlso6imk735ho.ok.kimi.link)（CraftifyX Miner 6.0 · 全栈创作者发现与进化系统）

---

## 本文档的作用

本文档将上述网页中的产品与系统设计说明**固化到本地仓库**，便于：

- **离线阅读与评审**：不依赖外网页面可用性，可在版本库内与 PR、Issue、实施计划对照。
- **对齐团队认知**：产品、数据、工程、BD 共用同一套术语（Layer-1/2、中心度、SPS、双轨飞轮等）。
- **作为实施蓝图**：与仓库内 `pipeline/`、`dashboard/`、数据表结构等实现逐条映射时的**单一事实来源（本地副本）**。

> 说明：文中运营数字、成本与 ROI 等均来自原页面**示例/估算**，实际以业务数据与落地配置为准。

---

## 核心内容（速览）

| 主题 | 一句话 |
|------|--------|
| **系统目标** | 从种子与社交关系出发，**日更**发现创作者，自动算 **10 维特征**与 **SPS**，结合**轻量中心度**支撑 **BD 决策**，并通过 **BD + 销售双反馈**月度进化。 |
| **发现机制** | **Multi-hop**：Layer-1（动态锚点 Following）+ Layer-2（超级连接器）+ **反向**（Tier S 粉丝），预算 **60% / 30% / 10%**。 |
| **排序与分层** | 按「被多少 Seed 关注」划分 **Hub / Connector / Peripheral**，再与 **SPS 阈值**组合定 BD 优先级。 |
| **数据与工程** | **7 张核心表**（创作者、推文、特征、图谱、评分、销售反馈、触达日志）；**Apify** 四类采集；示例 **6 周**上线路径与目录结构。 |
| **进化闭环** | **Track 1**：用回复率等优化 **Contact Probability**；**Track 2**：用 GMV 等校准 **SPS 权重**；高 GMV 账号可**晋升新 Seed**。 |

---

## 1. 产品定位与展示指标（原页示例）

**CraftifyX Miner 6.0** — 全栈创作者发现与进化系统 · 端到端解决方案。

原页展示的运营看板示例（非承诺指标）：

- **日发现量**：687  
- **候选池总量**：15,847  
- **本月 GMV**：$284K  
- **系统版本**：v6.0  

原页导航主题：三层飞轮、完整业务流程、Multi-hop Discovery、轻量中心度、10 维指标、BD Dashboard、数据 Schema、实施路线。

---

## 2. 三层飞轮 + 双轨进化架构

原页用流程图描述四层逻辑关系，本地文档用文字归纳如下（与 Mermaid 图等价）。

### 2.1 输入层：多源发现引擎

- **种子数据导入**：初始 100+ 经销售验证的创作者。  
- **Daily Multi-hop Discovery**：Layer-1 + Layer-2 + 反向挖掘。  
- **动态锚点选择**：**60% 利用**（偏已知高价值）+ **40% 探索**（偏高潜未成交）。

### 2.2 处理层：智能计算引擎

- **Apify 四类数据采集**：Profile / Tweets / Interaction / Followers。  
- **10 维指标计算**。  
- **轻量中心度分层**：Hub / Connector / Peripheral。  
- **SPS 评分** + **Contact Probability**。

### 2.3 应用层：BD 决策引擎

- **分级候选池**：Hub 优先 + SPS 排序。  
- **BD Dashboard**：Interested / Rejected / Deferred。  
- **联系执行与结果追踪**。

### 2.4 进化层：双轨飞轮

- **Track 1：BD 反馈** — 基于回复率优化 Contact 模型。  
- **Track 2：Sales 反馈** — 基于 GMV 训练 XGBoost 权重。  
- **新 Seed 晋升**：例如 GMV > $1000 自动入库。  
- **系统重训练**：月度权重校准。

**数据流（摘要）**：输入层各模块 → 处理层 B1→B2→B3→B4 → 应用层 C1→C2→C3 → 进化层 D1、D2 → D4；D2 → D3；D3 回到发现（如 A2）。

---

## 3. 双轨飞轮进化机制（原页伪代码）

### 3.1 Track 1：BD 反馈优化 — Contact Probability

基于回复率优化联系概率；原页示例逻辑：

```python
def monthly_contact_model_update():
    data = query("SELECT cs.contact_probability, o.response_received...")
    model = LogisticRegression().fit(X, y)
    update_contact_prediction_model(model)
    # 准确度预计提升至 82%（原页表述）
```

### 3.2 Track 2：Sales 反馈优化 — SPS 权重

基于 GMV 等目标训练 XGBoost，用特征重要性更新权重；原页示例：

```python
def monthly_sps_calibration():
    for creator_type in types:
        model = XGBRegressor().fit(X, y)
        importance = model.feature_importances_
        update_sps_weights(creator_type, importance)
```

---

## 4. 完整业务流程：从种子到飞轮

### P1 — 种子数据导入（Week 1）

- **输入**：`merged_creators.csv`（含销售数据、分类标签等）。  
- **目标**：约 100 个分级种子。  

**SQL 示例（原页）**：

```sql
COPY creators(username, total_sales, category, cart_rate)
FROM 'merged_creators.csv' CSV HEADER;

UPDATE creators
SET is_seed = true,
    seed_tier = CASE
        WHEN total_sales > 2000 THEN 'S'
        WHEN total_sales > 500  THEN 'A'
        ELSE 'C'
    END;
```

**原页示例 Tier 人数**：Tier S: 8 人；Tier A: 15；Tier B: 35；Tier C: 42。

### P2 — 初始 Graph 构建（Week 2）

- 基于约 **100** 个种子构建 Layer-1 网络。  
- **约 5,000** Layer-1 候选人；每人约 **500** Following；约 **50,000** 条 Graph 边。

### P3 — 每日 Multi-hop Discovery（持续）

- **Layer-1（60% 预算）**：动态锚点，抓取 Following。  
- **Layer-2（30% 预算）**：超级连接器 — 被 **≥3** 个 Seed 关注的创作者。  
- **反向（10% 预算）**：抓取 Tier S Seed 的创作者粉丝（带筛选）。  
- **产出量级（原页）**：约 **500–800 人/日**。

### P4 — 10 维指标与中心度计算（自动）

流程：**深度采集 → 特征计算 → 中心度分层 → SPS 评分**，全自动。

维度名称（原页）：Audience（规模）、Engagement（粘性）、Virality（爆款）、Posting（勤勉）、Monetization（变现）等（详见第 8 节矩阵）。

### P5 — BD Dashboard 决策流程（人机结合）

- **早 9 点**看日报 → **9:30–11:30** 人工判定 → **下午**联系执行。  
- **日审（原页示例）**：20–30 人。  
- 状态：**Interested / Rejected / Deferred**。

### P6 — 双轨飞轮进化（月度）

- BD 反馈优化 + Sales 反馈优化 + 新 Seed 晋升。  
- **每月 1 次**：Contact 模型、SPS 校准、GMV > $1000 晋升入库等。

---

## 5. Multi-hop 策略细节（原页）

### 5.1 Layer-1 — 常规扩展（60% 预算 · 每日早 8 点 · 主流程）

**动态锚点（原页伪代码）**：

```python
def select_dynamic_anchors():
    anchors = []
    # 60% 利用：高 GMV Seed
    high_gmv = query(
        "SELECT username FROM creators WHERE seed_tier IN ('S', 'A') LIMIT 12"
    )
    anchors.extend(high_gmv)
    # 40% 探索：高 SPS 未成交
    unexplored = query(
        "SELECT username FROM creator_scores WHERE sps_score > 80 AND total_sales IS NULL LIMIT 8"
    )
    anchors.extend(unexplored)
    return anchors
```

| 项 | 原页数值 |
|----|-----------|
| 锚点数量 | 20 个/日 |
| 抓取数量 | 500 Following/人 |
| 预期产出 | 300–400 人/日 |

### 5.2 Layer-2 — 超级连接器（30% 预算）

**识别（原页 SQL 思路）**：

```python
def identify_super_connectors():
    return query("""
        SELECT connected_creator_id, COUNT(*) AS centrality
        FROM creator_graph
        WHERE connection_type = 'follow'
        GROUP BY connected_creator_id
        HAVING COUNT(*) >= 3
        ORDER BY centrality DESC
        LIMIT 20
    """)
```

| 项 | 原页数值 |
|----|-----------|
| 识别标准 | 被 ≥3 个 Seed 关注 |
| 抓取数量 | 200 Following/人 |
| 预期产出 | 100–150 人/日 |

### 5.3 反向挖掘（10% 预算 · 每周 2 次）

```python
def crawl_reverse_followers():
    tier_s_followers = apify.crawl_followers(tier_s_seeds, max_items=1000)
    creator_followers = [
        f for f in tier_s_followers
        if has_creator_keywords(f["bio"])
        and 1000 < f["followers"] < 50000
    ]
    return creator_followers
```

| 项 | 原页数值 |
|----|-----------|
| 目标 | Tier S Seed 的粉丝 |
| 抓取数量 | 1000 Followers/人 |
| 预期产出 | 50–100 人/次 |

### 5.4 预算分配与产出汇总（原页）

| 占比 | 通道 | 成本（约） | 产出（约） |
|------|------|------------|------------|
| 60% | Layer-1 | ~$6/日 | 300–400 人 |
| 30% | Layer-2 | ~$3/日 | 100–150 人 |
| 10% | 反向 | ~$2/日 | 50–100 人/次 |
| — | **合计** | **~$10–15/日** | **500–800 人/日** |

---

## 6. 轻量中心度分层

基于「多少 Seed 关注该用户」，无需复杂图算法。

```python
def calculate_centrality_tier(username):
    seed_connections = query(f"""
        SELECT COUNT(DISTINCT creator_id) AS count
        FROM creator_graph
        WHERE connected_creator_id = '{username}'
          AND creator_id IN (SELECT id FROM creators WHERE is_seed = true)
    """)[0]["count"]

    if seed_connections >= 5:
        return "Hub"        # 被多个 Seed 认可
    if seed_connections >= 2:
        return "Connector"  # 连接节点
    return "Peripheral"     # 边缘节点
```

| 层级 | 条件 | 含义（原页） |
|------|------|----------------|
| **Hub** | 被 ≥5 个 Seed 关注 | 圈层核心，BD 优先，认可度高 |
| **Connector** | 被 2–4 个 Seed 关注 | 次级优先，有潜力成为 Hub |
| **Peripheral** | 被 0–1 个 Seed 关注 | 常规处理，依赖 SPS |

**原页示例候选池分布**：Hub **15**；Connector **127**；Peripheral **15,705**。

### BD 优先级排序策略（原页）

1. **第 1 优先级**：Hub + SPS > 80  
2. **第 2 优先级**：Connector + SPS > 75  
3. **第 3 优先级**：Peripheral + SPS > 75  

---

## 7. 10 维指标与权重矩阵（原页）

原页以雷达图对比多类创作者（OC、Vtuber、Fan Artist、Game Creator、Content Creator 等）。以下为**指标权重矩阵**（公式/规则摘要）。

| 指标 | 含义 | 计算要点（原页） |
|------|------|------------------|
| Audience Score | 规模 | log10(followers+1) × 20 |
| Engagement Score | 粘性 | (赞 + 转×2 + 评×3) / followers × 100 |
| Virality Score | 爆款 | top3_avg / monthly_avg，>5x → 100 |
| Posting Score | 勤勉 | 月发帖数 / 30 × 100 |
| Monetization Score | 变现 | Bio 关键词：商店 90 / 接单 60 / 无 0 |
| Growth Score | 增速 | 月环比粉丝增长 |
| Circle Influence Score（圈层影响力） | 被 Seed 认可程度 | 与 `creator_scores.seed_connections` 同源：统计有多少个 `is_seed=true` 的账号在 `creator_graph` 中关注该创作者；归一化 `min(100, seed_connections × 20)`（5 个及以上 Seed 关注 → 100，与 Hub 阈值对齐） |
| Character Consistency | IP 化 | pHash 最大聚类 / 总图片 × 100 |
| Community Score | 社区 | (mentions×2 + fanart×5) / 标准化 |
| Data Confidence | 置信 | 账号年龄×0.6 + 完整度×0.4 |

---

## 8. BD 审核工作台（原页示例）

**队列概览**：Hub: 15；Connector: 42；SPS>75: 68。

**列表字段（表头）**：创作者 | 中心度 | SPS | 关键信号 | 来源 | 操作  

### 今日日报（示例）

- 新候选总数：**687**  
- Hub 级高优：**15**  
- Connector 级：**42**  
- SPS>75 筛选：**68**  

### 本周追踪（示例）

- Interested（未联系）：15  
- Contacted（待回复）：8  
- Responded（洽谈中）：5  

### 进化洞察（示例）

- Contact Probability 准确度：**78%**（目标 >75%）  
- 权重校准建议：Character Consistency 提升至 **0.25**  

---

## 9. 七张核心数据表（原页）

| 表名 | 说明 | 主要字段（原页列举） |
|------|------|----------------------|
| **creators** | 创作者档案 | username, followers, bio, website, is_seed, seed_tier, total_sales, discovered_via, anchor_seed, bd_status |
| **tweets** | 推文数据 | tweet_id, likes, retweets, replies, views, text, media_urls, interaction_data (JSONB) |
| **creator_features** | 10 维指标 | audience_score, engagement_score, virality_score, growth_score, posting_score, monetization_score, circle_influence_score, character_consistency, community_score, data_confidence |
| **creator_graph** | 关系图谱 | creator_id, connected_creator_id, connection_type, weight |
| **creator_scores** | SPS + 中心度等 | creator_type, sps_score, confidence, centrality_tier, seed_connections, contact_probability, predicted_response_rate |
| **sales_feedback** | 进化核心 | sku_id, gmv, units_sold, launch_date, conversion_rate, bd_contact_id, days_to_close |
| **outreach_log** | BD 联系追踪 | bd_username, contact_channel, contacted_at, response_received, response_time_hours, deal_status |

### 数据规模预估（原页）

- creators ~**50,000**  
- tweets ~**2,500,000**  
- creator_graph ~**500,000**  
- sales_feedback ~**1,000/年**  

---

## 10. 项目结构（原页示意）

```
project/
├── config/
│   ├── apify_config.yaml
│   └── weights.yaml
├── pipeline/
│   ├── seed_import.py
│   ├── initial_graph.py
│   ├── daily_discovery.py
│   ├── feature_engine.py
│   └── evolution.py
├── dashboard/
│   └── app.py
├── models/
│   ├── contact_predictor.pkl
│   └── sps_weights.json
└── cron/
    └── daily_job.py
```

---

## 11. 六周实施路线图（原页）

| 周次 | 主题 | 交付要点 |
|------|------|----------|
| **W1** | 种子导入 | 部署 PostgreSQL；导入 merged_creators.csv；标记 Tier S/A/B/C |
| **W2** | 初始 Graph | 配置 Apify 4 个 Actor；抓取 100 Seed 的 Following；构建 ~5,000 人 Layer-1 |
| **W3** | 指标计算 | 开发 Feature Engine；计算 100 Seed 的 10 维指标；训练初始 SPS 权重 |
| **W4** | Dashboard | Streamlit 开发；BD 工作流测试；设置 outreach_log |
| **W5** | Daily Discovery | 部署 Multi-hop 自动化；配置动态锚点；启动 Layer-2 挖掘 |
| **W6** | 飞轮启动 | 录入首月 Sales 数据；第一次权重校准；新 Seed 自动晋升测试 |

---

## 12. 成本与 ROI 估算（原页）

| 项 | 数值（原页） |
|----|----------------|
| 月度成本 | **$414**（Apify $49 + 采集 $300 + 其他 $65） |
| 月发现量 | **~15,000**（500 人/日 × 30） |
| 预计成交 | **15–30** 人（按 10–20% 转化率） |
| 月度 GMV 增量 | **$75K–$150K** |
| 系统成本占 GMV | **~0.5%**（示例口径） |

---

## 13. 附录：与精简摘要的关系

仓库内另有精简版 **`CraftifyX-Miner-6.0-摘要.md`**，适合快速浏览；**本文档 `CraftifyX-Miner-6.0.md` 为与网页对应的完整本地副本**，并增加了文首「作用」与「核心内容」说明。

---

*本文档内容由在线说明页整理为 Markdown，便于本地版本管理；若原页更新，请同步修订本节与在线链接。*
