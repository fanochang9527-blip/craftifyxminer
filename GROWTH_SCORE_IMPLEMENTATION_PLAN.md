# Growth Score 功能开发计划

> 创建日期：2026-06-01  
> 背景：当前 `feature_engine.py` 中 `calc_growth()` 为硬编码占位函数（`return 50.0`），`creators.followers` 在每次扫描时被直接覆盖，无历史记录。本计划实现基于历史粉丝快照的真实增长率计算。

---

## 一、需求定稿（经多轮确认）

| # | 需求 | 状态 |
|---|------|------|
| 1 | **Dashboard 不做任何修改** | ✅ 定稿 |
| 2 | **新数据走原流程**：今天之后新 deep scrape 的创作者，Day 0 立即计算 8 维真实特征 + `growth_score` 占位（50.0），投入模型推理 | ✅ 定稿 |
| 3 | **额外记录粉丝历史**：新数据在走原流程的同时，每次 followers 被更新时顺手写入历史快照表 | ✅ 定稿 |
| 4 | **存量数据从今天开始积累**：从今天起，每次存量创作者被 L1 扫描/deep scrape 更新 followers 时，顺手写入历史快照表 | ✅ 定稿 |
| 5 | **30 天统一转正**：当 snapshot 表中积累了 **≥2 条记录** 且 **时间跨度 ≥30 天** 时，计算真实 `growth_score`，替换占位符，重新模型推理 | ✅ 定稿 |
| 6 | **种子用户独立表**：种子（`is_seed = true`）粉丝快照写入独立的 `seed_follower_snapshots` 表，30 天满后替换占位符，**触发 sellability + sps 全量模型训练** | ✅ 定稿 |
| 7 | **新种子训练限制**：`growth_score` 仍为占位符（50.0）的种子，不得参与模型训练 | ✅ 定稿 |

---

## 二、核心方案：零额外查询，纯被动积累

**不新增任何 Apify 调用**，完全复用现有的三个 followers 更新入口：

| 入口文件 | 现有行为 | 新增行为 |
|---------|---------|---------|
| `pipeline/intake.py` | L1 扫描更新 `creators.followers` | 顺手写 `creator_snapshots` |
| `pipeline/deep_scrape.py` | Deep scrape 更新 `creators.followers` | 顺手写 `creator_snapshots` / `seed_follower_snapshots` |
| `pipeline/seed_import.py` | 种子导入写入 `creators.followers` | 顺手写 `seed_follower_snapshots` |

**转正逻辑**：每日 cron 扫描 snapshot 表，用 SQL 找出满足"≥2 条且跨度 ≥30 天"的创作者，批量计算真实 growth，替换占位符。

---

## 三、数据库变更

### 3.1 新增表（`db/schema.sql` 追加）

```sql
-- 普通创作者粉丝历史快照
CREATE TABLE IF NOT EXISTS creator_snapshots (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
    observed_at TIMESTAMP DEFAULT NOW(),
    followers INTEGER,
    following INTEGER,
    tweets_count INTEGER,
    source VARCHAR(20),           -- 'intake' | 'deep_scrape' | 'seed_import' | 'backfill'
    anomaly_type VARCHAR(20),     -- 'sudden_drop' | NULL
    anomaly_note TEXT,
    UNIQUE(creator_id, observed_at)
);
CREATE INDEX idx_snapshots_creator_time ON creator_snapshots (creator_id, observed_at DESC);

-- 种子用户专属粉丝历史快照
CREATE TABLE IF NOT EXISTS seed_follower_snapshots (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
    observed_at TIMESTAMP DEFAULT NOW(),
    followers INTEGER,
    following INTEGER,
    source VARCHAR(20),           -- 'seed_import' | 'deep_scrape' | 'intake'
    batch_tag TEXT,
    UNIQUE(creator_id, observed_at)
);
CREATE INDEX idx_seed_snapshots_creator_time ON seed_follower_snapshots (creator_id, observed_at DESC);
```

### 3.2 迁移脚本

- **文件**：`db/migrations/009_growth_snapshots.sql`
- **内容**：执行上述两张建表语句，加 `IF NOT EXISTS` 保护

---

## 四、核心模块：`pipeline/growth_monitor.py`（新增）

### 4.1 `record_snapshot(creator_id, followers, following, tweets_count, source, is_seed=False)`

**调用方**：`intake.py` / `deep_scrape.py` / `seed_import.py`

**行为**：
- `is_seed=False` → 写入 `creator_snapshots`
- `is_seed=True` → 写入 `seed_follower_snapshots`
- 幂等：`ON CONFLICT (creator_id, observed_at) DO NOTHING`

### 4.2 `calc_growth(creator_id, is_seed=False) -> tuple[float, bool]`

**返回**：`(growth_score, is_real)`，`is_real=True` 表示基于真实历史计算。

**逻辑**：
1. 查对应 snapshot 表，按 `observed_at` 排序
2. 记录数 `< 2` → 返回 `(50.0, False)`
3. 记录数 `≥ 2`：取最早和最近两个点
   ```
   days = (latest.observed_at - earliest.observed_at).days
   if days < 30:
       return (50.0, False)   -- 跨度不足 30 天，继续占位
   growth_rate = (latest.followers - earliest.followers) / max(earliest.followers, 1)
   ```
4. **Anomaly 检测**：若 `earliest.followers > 1000` 且 `growth_rate < -0.80`，在 `latest` 快照行标记 `anomaly_type='sudden_drop'`，但**数据保留**。回退到倒数第二条正常数据计算；若无则返回占位值
5. 映射：`score = 50 + growth_rate * 100`，clamp 到 `[0, 100]`
6. 返回 `(score, True)`

### 4.3 `refresh_growth_scores() -> dict`

**调用方**：cron 每日 11:00

**行为**：
1. SQL 找出满足 30 天跨度的普通创作者：
   ```sql
   SELECT creator_id, MIN(observed_at) as first_at, MAX(observed_at) as last_at
   FROM creator_snapshots
   GROUP BY creator_id
   HAVING COUNT(*) >= 2 AND MAX(observed_at) - MIN(observed_at) >= INTERVAL '30 days'
   ```
2. SQL 找出满足 30 天跨度的种子用户（查 `seed_follower_snapshots`）
3. 对每个满足条件的创作者：
   - `calc_growth(creator_id, is_seed)` → `(score, is_real)`
   - 若 `is_real=True` 且当前 `creator_features.growth_score == 50.0`（占位）：
     - `UPDATE creator_features SET growth_score = score, calculated_at = NOW()`
     - 调用 `_run_single_inference(creator_id)` 重新模型推理
     - **若 `is_seed=True`**：额外调用 `runner.train_models()` 全量训练

> 注：已转正的创作者（growth 已为真实值）即使后续跨度变长，也不再触发模型重训练，避免频繁训练。

### 4.4 `_run_single_inference(creator_id)`

```python
features = fetch_one("SELECT * FROM creator_features WHERE creator_id = %s", (creator_id,))
if not features:
    return

from pipeline.sellability_model import predict_sellability
from pipeline.sps_model import predict_sps

sellability = predict_sellability(features)
sps = predict_sps(features)

with get_cursor() as cur:
    cur.execute(
        """INSERT INTO creator_scores (creator_id, sellability_score, sps_score, updated_at)
           VALUES (%s, %s, %s, NOW())
           ON CONFLICT (creator_id) DO UPDATE SET
               sellability_score = EXCLUDED.sellability_score,
               sps_score = EXCLUDED.sps_score,
               updated_at = NOW()""",
        (creator_id, sellability, sps),
    )
```

---

## 五、Pipeline 集成点（修改现有文件）

### 5.1 `pipeline/feature_engine.py`

**修改 `calc_growth()`**：
- 删除硬编码 `return 50.0`
- 接收 `creator_id` 和 `is_seed=False`
- 委托调用 `growth_monitor.calc_growth(creator_id, is_seed)`

**`compute_features_for_creator()` 保持不变**：
- Day 0 首次计算时，调用新版 `calc_growth()`
- 若 snapshot 不足 2 条或跨度 < 30 天，返回占位值 50.0
- 若已满足条件，返回真实值

### 5.2 `pipeline/deep_scrape.py`

**保持 `trigger_deep_scrape_batch()` 原有逻辑不变**（不分流，所有候选人都走原流程）。

**修改 `_store_deep_scrape_results()`**：
- 在 `UPDATE creators SET followers = ...` 成功后，同一事务内：
  ```python
  is_seed = fetch_one("SELECT is_seed FROM creators WHERE id = %s", (creator_id,))["is_seed"]
  growth_monitor.record_snapshot(
      creator_id=creator_id,
      followers=author_followers,
      following=author_following,
      tweets_count=author_tweets_count,
      source='deep_scrape',
      is_seed=is_seed,
  )
  ```

### 5.3 `pipeline/intake.py`

在 `store_dataset_items()` 的 `ON CONFLICT UPDATE` 更新 followers 后，同一事务内：

```python
creator_info = fetch_one("SELECT id, is_seed FROM creators WHERE platform_account_id = %s", (username,))
if creator_info and followers > 0:
    growth_monitor.record_snapshot(
        creator_id=creator_info["id"],
        followers=followers,
        following=following,
        tweets_count=tweets_count,
        source='intake',
        is_seed=creator_info["is_seed"],
    )
```

### 5.4 `pipeline/seed_import.py`

在 `import_seeds()` 中，每条种子记录写入 `creators` 表后：

```python
if followers > 0:
    growth_monitor.record_snapshot(
        creator_id=creator_id,
        followers=followers,
        following=following,
        tweets_count=tweets_count,
        source='seed_import',
        is_seed=True,
    )
```

### 5.5 `pipeline/sellability_model.py` + `pipeline/sps_model.py`

在 `_load_training_rows()`（sellability）和 `_load_training_data()`（sps）的 SQL 中，增加条件排除 growth 仍为占位的种子：

```sql
WHERE c.is_seed = true 
  AND c.total_sales > 0
  AND cf.growth_score IS DISTINCT FROM 50.0
```

> 用 `IS DISTINCT FROM` 正确处理 NULL 值。

---

## 六、Cron 调度

### 6.1 新增任务（`cron/daily_job.py`）

在现有任务后追加：

```python
@scheduler.scheduled_job("cron", hour=11, minute=0, id="growth_monitor", misfire_grace_time=3600)
def job_growth_monitor():
    from pipeline.growth_monitor import refresh_growth_scores
    result = refresh_growth_scores()
    logger.info("Growth refresh finished: %d checked, %d graduated", 
                result.get("checked", 0), result.get("graduated", 0))
```

---

## 七、存量回填

### 7.1 一次性脚本（`scripts/backfill_snapshots.py`，新增）

首次部署时手动运行：

```python
def backfill_all():
    rows = fetch_all("SELECT id, followers, following, tweets_count, is_seed, first_seen_at FROM creators WHERE followers > 0")
    for r in rows:
        table = "seed_follower_snapshots" if r["is_seed"] else "creator_snapshots"
        observed = r["first_seen_at"] or datetime.now()
        execute(f"""
            INSERT INTO {table} (creator_id, followers, following, tweets_count, source, observed_at)
            VALUES (%s, %s, %s, %s, 'backfill', %s)
            ON CONFLICT DO NOTHING
        """, (r["id"], r["followers"], r["following"], r["tweets_count"], observed))
```

> 回填后，存量创作者下次被 L1/deep_scrape 刷新时，snapshot 表中就有第二个时间点。若 30 天内未被刷新，则不满足转正条件，保持占位。

---

## 八、配置更新

### 8.1 `config/settings.py` + `.env.example`

新增环境变量（全部带默认值，向后兼容）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GROWTH_SPAN_MIN_DAYS` | `30` | 计算 growth 所需的最小时间跨度（天） |
| `GROWTH_ANOMALY_DROP_THRESHOLD` | `-0.80` | 粉丝骤降异常阈值 |
| `GROWTH_ANOMALY_MIN_FOLLOWERS` | `1000` | 异常检测最小粉丝数 |

---

## 九、测试

### 9.1 新增测试文件：`tests/test_growth_monitor.py`

覆盖场景：
- `record_snapshot` 幂等性（同一 `creator_id + observed_at` 不重复写入）
- `calc_growth`：
  - 0/1 条 snapshot → 占位 50.0
  - 2 条但跨度 < 30 天 → 占位 50.0
  - 2 条跨度 ≥ 30 天 → 真实值
  - 正常增长 20% → score=70
  - 骤降 90% → 标记 anomaly，回退占位
- `refresh_growth_scores`：只更新占位 → 真实，不重复更新已真实的值
- 训练 SQL 排除：`growth_score = 50.0` 的种子不出现在训练数据中

---

## 十、数据流时序图

### 存量创作者（今天之前已在库）

```
Today (Day 0):   backfill_snapshots.py 写入初始 snapshot（observed_at = first_seen_at）
                 └─► growth_score = 50.0（保持占位）

Day N:           L1 扫描 或 Deep Scrape 更新 followers
                 └─► 顺手写入 creator_snapshots（observed_at = NOW()）

Day M (M-N ≥ 30): refresh_growth_scores() 检测到跨度 ≥30 天
                 ├─► calc_growth() → 真实 growth_score
                 ├─► UPDATE creator_features.growth_score
                 └─► _run_single_inference() → 重新推理 sellability + sps
```

### 新创作者（今天之后入库）

```
Day 0:  Deep Scrape → 入库 tweets/creators
        ├─► compute_features_for_creator() → 8维真实 + growth占位(50)
        ├─► 模型推理（growth用占位值）
        └─► 顺手写入 creator_snapshots

Day 30 (next deep_scrape): 再次更新 followers
        ├─► 写入 creator_snapshots（第二个时间点，跨度≈30天）
        └─► refresh_growth_scores() 检测到满足条件
            ├─► calc_growth() → 真实 growth_score
            ├─► UPDATE creator_features.growth_score
            └─► _run_single_inference() → 重新推理（growth用真实值）
```

### 种子用户

```
Day 0:  Seed Import → 入库 creators
        ├─► 顺手写入 seed_follower_snapshots
        └─► growth_score = 50.0（占位，不参与模型训练）

Day 30: 再次扫描更新 followers
        ├─► 写入 seed_follower_snapshots
        └─► refresh_growth_scores() 检测到满足条件
            ├─► calc_growth() → 真实 growth_score
            ├─► UPDATE creator_features.growth_score
            ├─► _run_single_inference() → 重新推理
            └─► runner.train_models() → 全量重训练 sellability + sps
```

---

## 十一、实施顺序

| 顺序 | 文件 | 动作 |
|------|------|------|
| 1 | `db/schema.sql` + `db/migrations/009_growth_snapshots.sql` | 建表 |
| 2 | `config/settings.py` + `.env.example` | 新增配置 |
| 3 | `pipeline/growth_monitor.py`（新增） | 核心模块 |
| 4 | `pipeline/feature_engine.py` | 修改 `calc_growth()` |
| 5 | `pipeline/deep_scrape.py` | 顺手写 snapshot |
| 6 | `pipeline/intake.py` | 顺手写 snapshot |
| 7 | `pipeline/seed_import.py` | 顺手写 snapshot |
| 8 | `pipeline/sellability_model.py` + `pipeline/sps_model.py` | 训练 SQL 加排除条件 |
| 9 | `cron/daily_job.py` | 新增 11:00 定时任务 |
| 10 | `scripts/backfill_snapshots.py`（新增） | 存量回填（部署后手动跑） |
| 11 | `tests/test_growth_monitor.py`（新增） | 测试 |

---

## 十二、成本与风险

- **零新增 Apify 成本**：完全复用现有 L1/deep_scrape/seed_import 的 followers 更新频率，不增加任何额外 API 调用
- **数据库增量**：snapshot 表随既有扫描频率增长，deep_scrape 每 30 天一次、L1 扫描不定期，数据量可控
- **模型训练频率**：仅种子用户的 growth_score **首次**从占位变真实时触发一次训练，之后不再训练
- **存量转正延迟**：取决于创作者下次被扫描的时间。若一个存量创作者 30 天内未被 L1/deep_scrape 触及，则无法转正。这是被动积累的固有特性
- **Dashboard 零改动**：anomaly 数据存在 snapshot 表中，不展示

---

## 十三、关键代码上下文（供新会话快速理解）

### 现有 followers 更新入口位置

1. **`pipeline/intake.py:89-104`** — L1 扫描时 `INSERT INTO creators ... ON CONFLICT UPDATE SET followers = EXCLUDED.followers`
2. **`pipeline/deep_scrape.py:85-96`** — `_store_deep_scrape_results()` 中 `UPDATE creators SET followers = COALESCE(%s, followers)`
3. **`pipeline/seed_import.py:157-166`** — `import_seeds()` 中 `INSERT INTO creators ... is_seed = true`

### 现有模型训练入口

1. **`pipeline/sellability_model.py:151`** — `train_model()`
2. **`pipeline/sps_model.py:86`** — `train_model()`
3. **`pipeline/runner.py:270`** — `train_models()` 同时调用两者

### 现有模型推理入口

1. **`pipeline/sellability_model.py:290`** — `predict_sellability(features_row)`
2. **`pipeline/sps_model.py:248`** — `predict_sps(features_row)`
3. **`pipeline/sps_scorer.py:133`** — `score_creator(creator_id)` 计算完整 SPS 相关分数

### 现有特征计算入口

1. **`pipeline/feature_engine.py:211`** — `calc_growth()` 当前为硬编码 `return 50.0`
2. **`pipeline/feature_engine.py:302`** — `compute_features_for_creator(creator_id)` 计算全部 9 维特征

### 现有 Cron 调度

**`cron/daily_job.py`**：
- 08:00 — 全链路 pipeline
- 09:00 — backfill_graph
- 10:00 — backfill_features
- 23:00 — daily_summary + promote_seeds

> 新增 11:00 — growth_monitor

### Apify Actor 配置

**`config/apify_config.yaml`**：
- `following_actor`：`apidojo/twitter-user-scraper`（L1 扫描）
- `profile_actor`：`apidojo/tweet-scraper`（Deep Scrape）
- `followers_actor`：`apidojo/twitter-user-scraper`（getFollowers=true）
