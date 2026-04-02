# 发现者：爬取与过滤流程说明

> 本文档依据当前仓库实现整理，便于需求方对照产品与代码。  
> 对应模块：`pipeline/discovery.py`、`pipeline/intake.py`、`pipeline/bio_rule_filter.py`、`pipeline/ai_filter.py`、`pipeline/deep_scrape.py`、`pipeline/runner.py`、`server/webhook.py`、`config/settings.py`、`config/apify_config.yaml`、`config/bio_rules.yaml`。

---

## 一、端到端总览

发现链路在 `pipeline/runner.py` 的 `run_full_pipeline()` 中按顺序执行，大致为：

1. **生成当日锚点** → 2. **L1：Following 浅层爬取（Apify）** → 3. **入库** → 4. **规则 + AI 过滤** → 5. **发现来源打标** → 6. **深度抓取（推文+画像）** → 7. **特征计算** → 8. **SPS 评分**

其中「发现者」核心指 **1～5**（锚点、L1、入库、过滤、溯源）；6～8 为下游 enrichment，常与发现链路一并关注。

另有一条 **Webhook 异步路径**（`server/webhook.py`）：Apify 完成后回调，只跑 **入库 + 过滤**（`process_dataset`），**不会**执行 `discovery.py` 里的「批次打标」逻辑。

---

## 二、环节 1：每日锚点生成（`generate_daily_seeds`）

**文件**：`pipeline/discovery.py`  

**目的**：决定「今天从哪些人出发去扫 Following」，并写入 `discovery_batches` 做批次记录。

### 2.1 数量与比例（环境变量）

| 配置项 | 默认值（`config/settings.py`） | 含义 |
|--------|-------------------------------|------|
| `DAILY_ANCHOR_COUNT` | 20 | 当日锚点总数 |
| `EXPLORATION_RATIO` | 0.20（20%） | 探索锚点占比 |

- **常规锚点数** = `总数 - explore_count`
- **探索锚点数** = `max(1, int(总数 × EXPLORATION_RATIO))`（即至少 1 个探索位，当总数很小时）

### 2.2 常规锚点（strategy = `seed_following`）

- 从 `creators` 中选：`is_seed = true` 且 `seed_tier IN ('S', 'A')`，限制条数为「常规」配额。
- 若 S/A 不够，再随机补 `seed_tier = 'B'`，直到凑满常规数量。
- 每条锚点结构：`{username, strategy: "seed_following", seed_id}`。

（代码中有「按最近一次出现在 `discovery_batches.anchor_seeds` 里轮换」的意图，但子查询参数为占位，**实际排序对需求可理解为：优先 S/A，不足补 B**。）

### 2.3 探索锚点（三种 strategy 轮询）

对「探索」配额，按索引 **循环** 使用三种策略：`geo_explore` → `hashtag_explore` → `time_explore` → 再循环……

| 策略 | 规则 |
|------|------|
| **time_explore** | 从任意 `is_seed = true` 里 **随机 1 个** Seed，用其 `username` 作为锚点（带 `seed_id`）。 |
| **geo_explore / hashtag_explore** | 从内置列表里 **随机选一个以 `#` 开头的标签** 当作 `username` 字段（`seed_id = None`）。 |

内置标签示例（节选，完整见代码中 `EXPLORE_HASHTAGS`）：

- 地域向：`#絵描きさんと繋がりたい`、`#그림쟁이와_소통해요`、`#ArtistOnTwitter`
- 品类向：`#indiegame`、`#gamedev`、`#VTuber`、`#plushie`、`#enamelpin`

### 2.4 批次落库

插入 `discovery_batches`：`batch_type = 'daily_l1'`，`anchor_seeds` = 当日全部锚点用户名列表，`exploration_ratio` = `EXPLORATION_RATIO`，`raw_discovered` 初始为 0。

---

## 三、环节 2：L1 Following 爬取（`trigger_l1_scan`）

**文件**：`pipeline/discovery.py`

### 3.1 预算门禁

- 查询 `cost_tracking` 当日 `SUM(apify_cost_usd)`。
- 若 **≥ `DAILY_APIFY_BUDGET_USD`**（默认 20 USD），**不启动** Actor，返回 `runs_started: 0, budget_ok: False`。

### 3.2 传给 Apify 的「句柄」规则（重要）

- `handles = [锚点.username for 锚点 in anchors if not username.startswith("#")]`
- **以 `#` 开头的探索锚点不会进入本次 Following 请求**（仅 `@` 用户句柄会参与）。
- 若过滤后 **没有任何有效句柄**，直接返回，不进行 L1 爬取。

### 3.3 Actor 与参数（`config/apify_config.yaml`）

- **Actor**：`apidojo/twitter-user-scraper`
- **输入**：`getFollowing: true`，`getFollowers: false`
- **每条锚点最多拉取 Following 条数**：`MAX_FOLLOWING_PER_ANCHOR`（默认 500），可由 `trigger_l1_scan(max_following=...)` 覆盖（如冒烟用 30～50）。

### 3.4 执行方式

- `client.actor(actor_id).call(run_input=...)` **同步等待**跑完。
- 用返回的 `defaultDatasetId` 拉全量 items，进入下一环节。

---

## 四、环节 3：入库（`store_dataset_items`）

**文件**：`pipeline/intake.py`

### 4.1 用户名解析

从每条 item 取（按顺序）：`username` / `screen_name` / `userName`，去 `@`、转小写；空则跳过。

### 4.2 写入字段

`bio`、`website`、`followers`、`following`、`tweets_count` 等从 item 的多种字段名兼容读取。

### 4.3 Upsert 规则

- `INSERT ... ON CONFLICT (username) DO UPDATE`：
  - `bio` / `website`：**仅当新值非空** 才覆盖（`COALESCE(NULLIF(EXCLUDED...), 旧值)`）。
  - `followers` / `following` / `tweets_count`：用新值覆盖。

### 4.4 默认状态

新插入行的 `bd_status` 由表默认 **`pending`**（见 `db/schema.sql`）；`discovered_date` 默认当天。

---

## 五、环节 4：过滤管道（`run_filter_pipeline`）

**文件**：`pipeline/intake.py`，规则实现：`pipeline/bio_rule_filter.py`，AI：`pipeline/ai_filter.py`

### 5.1 谁会被过滤

- 仅处理 **`bd_status = 'pending'`** 且 **`bio` 非空** 的用户。
- L1 同步路径里若传入 `usernames`，则 **再限制在该批 username 内**。
- **Bio 为空**：本管道**不会**更新 `bd_status`，保持 `pending`。

### 5.2 Level 1/2：规则快筛（`BioRuleFilter`）

配置：`config/bio_rules.yaml`。

**输入文本**：`bio + " " + website` 转小写；Emoji 匹配用原始 `bio`。

**判定顺序概要**：

1. **Link DNA（高置信）**  
   - `link_dna.high_confidence` 中任一条目出现在文本中 → **`passed: True`**，level 1，置信度 0.95，并做类型分类。

2. **误杀防范（先于关键词匹配）**  
   - `false_positive_rules`：fan 账号、工作室/团队等信号命中 → **`passed: False`**，level 2。

3. **身份词（identity_keywords，多语言合并）**  
   - 任一命中 → **`passed: True`**，level 2。

4. **组合条件（level 2 通过）**  
   - （动作词 **且** 工具词）或  
   - 弱信号 **≥ 2 个** 或  
   - （动作词 **且** Emoji 命中）  
   → **`passed: True`**。

5. **中等置信链接 + 任意组合信号**  
   - `medium_confidence`（如 twitch、youtube `@`、instagram）且上一步的 `combined` 非空 → **`passed: True`**。

6. 以上皆不满足 → **`passed: None`**（灰区），进入 Level 3。

**类型分类**：按 `type_classification` 首条匹配；否则默认 `content_creator`。

### 5.3 Level 3：AI 过滤（`AIFilter`）

- 仅处理规则返回 **`passed is None`** 的候选人。
- 批量调用 OpenAI 兼容 Chat API（默认 Moonshot Kimi 等，见 `FALLBACK_CHAIN`）。
- 模型输出 YES → `bd_status = 'ai_passed'`；NO → `ai_rejected`。
- 解析失败或缺条：该条按 **NO** 处理（见 `ai_filter.py` 中补全逻辑）。

### 5.4 状态写入

| 规则结果 | `bd_status` |
|----------|-------------|
| 规则 True | `rule_passed` |
| 规则 False | `rule_rejected` |
| 灰区 + AI YES | `ai_passed` |
| 灰区 + AI NO | `ai_rejected` |

---

## 六、环节 5：发现来源打标（`tag_discovery_source` / `_tag_batch`）

**时机**：在 `process_dataset` **之后**，由 `trigger_l1_scan` 调用（Webhook 路径**无此步**）。

**规则**：

- 对本次涉及的用户名集合，执行 `UPDATE`：  
  `discovery_strategy`、`anchor_seed`、`discovered_via`
- **仅当 `discovery_strategy IS NULL` 时更新**（避免覆盖已有溯源）。

**`_tag_batch` 的取值逻辑**：

- 在**非 `#` 开头**的锚点里统计各 `strategy` 出现次数，取 **众数** 作为整批的 `discovery_strategy`（若为空则默认 `seed_following`）。
- `anchor_seed`：至多列出前 5 个 `@handle`，多于 5 个则追加 `(+N)`。
- `discovered_via`：`l1_batch:{Apify_run_id}`。

**注意**：因策略按「非话题锚点」计数，若批次里话题类锚点未进 Apify，整批 `discovery_strategy` 可能主要反映 **Seed 句柄**侧。

---

## 七、环节 6：深度抓取（`trigger_deep_scrape_batch`）

**文件**：`pipeline/deep_scrape.py`

**入选条件**：

- `bd_status IN ('rule_passed', 'ai_passed')`
- 且该创作者 **尚无任何 `tweets` 记录**（`id NOT IN (SELECT DISTINCT creator_id FROM tweets ...)`）
- 按 `first_seen_at ASC` 取一批，批量大小 `DEEP_SCRAPE_BATCH_SIZE`（默认 50）。

同样受 **当日 Apify 预算** 门禁；通过则用 `profile_actor`（`apidojo/tweet-scraper`）拉推文并回写 `creators` + `tweets`，并更新当日最近一条 `discovery_batches.after_deep_scrape`。

---

## 八、环节 7～8：特征与 SPS（下游）

**文件**：`pipeline/feature_engine.py`、`pipeline/sps_scorer.py`

- **特征**：对所有 **已有推文、尚无 `creator_features`** 的创作者计算 10 维特征。
- **SPS**：对所有 **已有特征、尚无 `creator_scores`** 的创作者打分。

与「发现过滤」无额外规则门槛，依赖深度抓取是否已产生 `tweets`。

---

## 九、需求方易混淆点小结

1. **探索话题（#）**：生成锚点时会写入批次，但 **不会进入 Apify Following 请求**；当日若常规句柄也被预算/逻辑清空，可能出现「批次含话题但实际未扫 Following」的情况。
2. **Webhook**：只跑入库 + 过滤，**没有** `l1_batch` 打标。
3. **空 Bio**：不参与规则/AI 过滤，长期保持 `pending`。
4. **粉丝区间、去机器人**：当前 `intake`/规则里**没有**实现文档里常见的 `1000 < followers < 100000` 或 bot 检测；若产品需要，需另列需求。

---

## 相关代码路径速查

| 能力 | 路径 |
|------|------|
| 锚点 + L1 | `pipeline/discovery.py` |
| 入库 + 过滤 | `pipeline/intake.py` |
| 规则 | `pipeline/bio_rule_filter.py`、`config/bio_rules.yaml` |
| AI | `pipeline/ai_filter.py` |
| 深度抓取 | `pipeline/deep_scrape.py`、`config/apify_config.yaml` |
| 全流程入口 | `pipeline/runner.py` |
| Webhook | `server/webhook.py` |
| 默认阈值 | `config/settings.py` |
