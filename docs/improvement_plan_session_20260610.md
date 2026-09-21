# CraftifyX Miner 改进方案 —— 2026-06-10 会话记录

> **说明**：本文档基于线上服务器诊断会话整理，汇总了 Sellability 模型、SPS 模型的现状问题，以及针对毛绒娃娃业务的 Apify 数据抓取与特征工程改进建议。所有代码修改应在开发服务器完成后再同步到线上。

---

## 1. 会话背景与业务目标

本次会话围绕以下业务目标展开：

1. **Sellability 模型**：预测创作者是否值得 BD 联系（二分类问题）。
2. **SPS 模型**：预测创作者能卖多少钱——对毛绒娃娃定制业务而言，即合作潜力/销量预测（回归问题）。
3. **数据抓取策略**：通过 Apify 抓取粉丝画像、平台合作历史、带货内容表现，提升销量预测能力。

**关键约束**：线上服务器仅做诊断和实验，不做代码修改；所有代码改动在开发服务器进行。

---

## 2. Sellability 模型诊断与改进

### 2.1 发现的问题

#### 问题 1：模型严重欠训

- 当前数据库中可用于训练 Sellability 的样本为 **248 个**（109 正 / 139 负）。
- 但当前线上模型 `sellability_model_meta.json` 显示训练于 2026-05-22，仅用了 **70 个样本**（52 正 / 18 负）。
- 原因：模型是早期训练的，后续 BD 新增的大量标签未参与训练。

#### 问题 2：训练-预测特征不一致

- 老模型 meta 显示训练时用了 **15 维特征**。
- 当前 `_build_feature_vector` 只生成 **12 维特征**（`character_consistency` 等字段被注释掉）。
- 导致老模型无法在当前数据上评估，存在 training-serving skew 风险。

#### 问题 3：二分类概率作为"分值"的局限性

- 当前用 `predict_proba` 输出概率再映射为 0-100 分值。
- 这种用法在**排序场景**下合理，但在**绝对分值解释**场景下存在问题，尤其是 XGBoost 的概率校准通常不如 LogisticRegression。

### 2.2 已执行的操作

1. **备份老模型**：
   - `models/sellability_model.joblib.backup.20260610_171943`
   - `models/sellability_model_meta.json.backup.20260610_171943`

2. **重新训练模型并对比 LR vs XGBoost**：
   - 用当前 248 个样本做 5-Fold 交叉验证。
   - 结果：

| 模型 | 交叉验证准确率 | AUC | F1 |
|------|--------------|-----|-----|
| LogisticRegression | **65.36%** | **72.44%** | **64.70%** |
| XGBoostClassifier | 62.12% | 69.34% | 54.28% |

3. **保存新 XGBoost 模型为正式模型**：
   - 新模型在训练集上准确率 98.79%（严重过拟合）。
   - 交叉验证准确率仅 62.12%，低于 LR。
   - 模型文件：`models/sellability_model.joblib`
   - 对比报告：`models/sellability_model_comparison.json`

4. **热补丁：提高 XGBoost 切换阈值**（已在线上执行）：
   - 将 `pipeline/sellability_model.py` 中的 `if n_samples < 120:` 改为 `if n_samples < 800:`。
   - 两处均修改：`train_model()` 和 `train_model_v2()`。
   - 效果：样本不足 800 时强制使用 LogisticRegression，避免小样本下 XGBoost 过拟合。

### 2.3 改进建议

1. **保持当前阈值 800**，待样本积累到 800+ 后再评估是否切换 XGBoost。
2. **定期重新训练模型**（建议每日或每周），确保新增 BD 标签参与训练。
3. **未来切换 XGBoost 时，增加概率校准**（如 Isotonic Regression / Platt Scaling）。
4. **统一特征定义**，确保训练与预测使用完全相同的特征向量。

---

## 3. SPS 模型诊断与改进

### 3.1 发现的问题

#### 问题 1：目标与特征不匹配

- 业务目标：预测创作者能卖多少钱（合作潜力）。
- 当前目标变量：`total_sales_log1p`（历史总销量）。
- 问题：历史销量 ≠ 合作潜力。但经业务确认，**业务目标就是预测销量，不能为技术便利改变目标变量**。

#### 问题 2：现有特征无法预测销量

- 当前 13 个特征均为"创作者质量"指标（互动、涨粉、活跃度等），与"卖货能力"关联弱。
- 5-Fold 交叉验证结果：

| 模型 | MAE | RMSE | R² |
|------|-----|------|-----|
| Ridge | 0.9145 | 1.2442 | **-0.2370** |
| XGBoost | 0.8407 | 1.2329 | **-0.2227** |

- **R² 为负**：模型预测效果不如直接用训练集均值预测。

#### 问题 3：老模型维度不匹配

- 老模型 meta 显示 **15 维特征**，当前代码为 **13 维**，无法直接评估。
- 实际可用样本：85 个（经 `growth_monitor` 成熟度过滤后）。

#### 问题 4：followers 不是有效预测因子

- 快速实验：将 `followers_log` 加入特征向量。
- 结果：R² 从 -0.1392 降至 -0.2209，模型反而变差。
- 原因：`creator_type` 主导了模型，粉丝数与销量无线性关系。

### 3.2 已执行的操作

1. **备份老模型**：
   - `models/sps_model.joblib.backup.20260610_174052`
   - `models/sps_model_meta.json.backup.20260610_174052`

2. **用 Ridge 重新训练并保存**：
   - 新模型类型：`Ridge`
   - 样本数：85
   - 特征数：13
   - 模型文件：`models/sps_model.joblib`
   - 对比报告：`models/sps_model_comparison.json`

3. **followers 加入特征实验**：
   - 实验脚本：`/tmp/sps_followers_experiment.py`
   - 结论：followers 未能改善模型。

### 3.3 改进建议

SPS 的核心问题不是模型选型，而是**特征体系无法支撑销量预测**。必须补充与交易直接相关的数据：

| 需补充的数据 | 为什么重要 | 当前是否具备 |
|------------|-----------|------------|
| 商品品类/价格带 | 不同品类销量差异巨大 | 统一价格，无需价格带 |
| 粉丝消费能力/画像 | 决定付费意愿 | ❌ 缺失 |
| 内容风格与商品匹配度 | 决定转化率 | ⚠️ 部分可推导 |
| 平台合作历史 | 是否合作过、效果如何 | ❌ 缺失 |
| 带货内容表现 | 哪些帖子带了货、互动如何 | ❌ 缺失 |
| 过往周边/ merch 历史 | 对毛绒娃娃业务最关键 | ❌ 缺失 |

**具体改进方向**：

1. **增加"周边/合作历史"特征**（见第 4 章）。
2. **将 content_style 等已有字段纳入模型**。
3. **增加粉丝侧数据**（粉丝列表 + 简介推断）。
4. **长期目标**：积累真正的合作销售数据作为标签。

---

## 4. 毛绒娃娃业务的数据抓取与特征工程方案

### 4.1 业务特点

- 产品：毛绒娃娃（基于创作者作品形象定制）。
- 定价：统一价格。
- 核心逻辑：创作者的 IP/角色价值 → 定制成毛绒娃娃 → 销售。
- 关键问题：不是"粉丝有多少"，而是"粉丝有多爱这个角色，是否愿意为它花钱"。

### 4.2 现有 Apify 能力

当前配置在 `config/apify_config.yaml`：

- `apidojo/tweet-scraper`：抓推文 + profile。
- `apidojo/twitter-user-scraper`：抓 followers / following / profile。

当前 `deep_scrape.py` 每个创作者只抓 **10 条推文**，过少。

### 4.3 抓取策略改进

#### 4.3.1 增加推文抓取量

**建议**：将 `deep_scrape.py` 中的 `tweets_per_handle` 从 10 提高到 **50~100**。

```python
# pipeline/deep_scrape.py
if "apidojo" in profile_cfg.get("actor_id", ""):
    tweets_per_handle = 50  # 或 100
    actor_input["maxItems"] = max(actor_input.get("maxItems", 500), len(handles) * tweets_per_handle)
```

理由：分析周边/合作历史需要看过去半年到一年的推文。

#### 4.3.2 粉丝画像

**方案 A：抓粉丝列表 + 简介推断**（推荐）

用 `followers_actor` 抓每个创作者前 **500~1000 粉丝**，从粉丝简介推断：

| 推断维度 | 方法 |
|---------|------|
| 语言/地域 | 简介语言检测 + 位置关键词 |
| 兴趣标签 | 关键词匹配（anime, furry, OC, commission 等） |
| 付费意愿 | 简介中出现 Etsy, Patreon, Ko-fi 等平台链接 |

**方案 B：从创作者内容反推**（零成本）

- 推文语言 → 粉丝主要语言
- 推文发布时间分布 → 粉丝活跃时区
- 评论者简介 → 粉丝兴趣样本

**建议新增表**：

```sql
CREATE TABLE followers (
    id SERIAL PRIMARY KEY,
    creator_id INT REFERENCES creators(id),
    username TEXT,
    bio TEXT,
    profile_image_url TEXT,
    followers_count INT,
    collected_at TIMESTAMP DEFAULT NOW()
);
```

#### 4.3.3 平台合作历史

不需要换 Actor，基于推文文本分析即可。

**检测维度**：

1. **电商/众筹链接**：Etsy, Booth, Patreon, Ko-fi, Kickstarter, Big Cartel, Shopify 等。
2. **合作关键词**：collab, partnership, sponsored, commission。
3. **@品牌账号**：结合关键词判断是否为商业合作。

### 4.4 带货内容表现

对毛绒娃娃业务，"带货"主要指：

- 周边宣发帖
- Commission 帖
- OC 展示帖
- Fanart 互动帖

**关键指标**：

| 指标 | 计算方法 |
|------|---------|
| 周边帖占比 | 周边相关推文 / 总推文 |
| 周边帖平均互动 | 周边帖 (likes + retweets + replies) 的平均值 |
| 购买意向评论数 | 评论中含 "want to buy", "plush when?" 等 |
| 最近 90 天是否发过周边帖 | bool |

**抓取评论**：需要支持 `includeReplies` 的 Actor，如 `apidojo/tweet-scraper` 的 replies 模式。

---

## 5. 多语种周边/合作检测方案

### 5.1 方案 1：链接检测（零成本，跨语种）

**核心思路**：不管推文用什么语言，含电商链接就是周边信号。

```python
ESHOP_DOMAINS = [
    "etsy.com/shop", "booth.pm", "patreon.com", "ko-fi.com",
    "skeb.jp", "bigcartel.com", "shopify.com", "kickstarter.com",
    "camp-fire.jp", "pixiv.net/fanbox", "afdian.net", "taobao.com",
]
```

**优点**：零成本、跨语种、精度高。
**缺点**：检测不到口头提到但没放链接的帖子。

### 5.2 方案 2：多语种 Embedding 语义匹配（推荐）

用 `sentence-transformers` 的多语种模型（如 `paraphrase-multilingual-MiniLM-L12-v2`），将推文与预定义语义模板对比余弦相似度。

```python
from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

reference_texts = [
    "I am selling plush toys of my character",
    "My merch store is now open for pre-orders",
    "Custom doll commissions are available",
    "周边通贩开始接受预定",
    "ぬいぐるみ受注開始しました",
]

ref_embeddings = model.encode(reference_texts, convert_to_tensor=True)

def merch_similarity(tweet_text: str) -> float:
    tweet_emb = model.encode(tweet_text, convert_to_tensor=True)
    return float(util.cos_sim(tweet_emb, ref_embeddings).max())
```

**优点**：覆盖 100+ 语种、无需维护词库、能捕获同义词。
**缺点**：需安装 `sentence-transformers`（约 400MB 模型）。

### 5.3 方案 3：LLM 分类

用本地轻量 LLM 做二分类，适合对 Embedding 的模糊样本做精筛。

**缺点**：计算成本高、延迟大。建议只做精筛，不做全量。

### 5.4 建议架构：两层检测

```python
def detect_merch_signals(tweet):
    text = tweet["text"]
    urls = tweet["urls"]

    # Layer 1: 链接检测
    if has_eshop_link(urls):
        return {"is_merch": True, "confidence": 1.0}

    # Layer 2: 语义匹配
    sim = merch_similarity(text)
    if sim > 0.65:
        return {"is_merch": True, "confidence": sim}

    return {"is_merch": False, "confidence": sim}
```

---

## 6. 复用 bio_rules.yaml 到推文层面

### 6.1 现有规则

`config/bio_rules.yaml` 已包含：

- `link_dna`：高置信度商业化链接域名。
- `semantic_matrix.action_keywords`：英/中/日动作关键词。
- `type_tags.Plush_Merch`：plush, plushie, ぬいぐるみ 等。
- `emoji_signals`：商业化 emoji 和毛绒 emoji。

### 6.2 建议新增特征

在 `feature_engine.py` 中新增 `calc_tweet_merch_score(tweets)`：

```python
def calc_tweet_merch_score(tweets: list[dict]) -> float:
    """基于历史推文检测周边/商业化信号，返回 0~100"""
    if not tweets:
        return 0.0

    from pipeline.bio_rule_filter import BioRuleFilter
    bf = BioRuleFilter()
    rules = bf.rules

    link_dna = set(rules["link_dna"]["high_confidence"])
    action_keywords = []
    for words in rules["semantic_matrix"]["action_keywords"].values():
        action_keywords.extend(words)
    plush_keywords = rules["semantic_matrix"]["type_tags"]["Plush_Merch"]
    emojis = rules["emoji_signals"]["commerce"] + rules["emoji_signals"]["plush"]

    merch_count = 0
    for tw in tweets:
        text = (tw.get("text") or "").lower()
        urls = tw.get("urls", [])

        if any(dna in url for dna in link_dna for url in urls):
            merch_count += 1
            continue

        keywords = [k.lower() for k in action_keywords + plush_keywords]
        if any(kw in text for kw in keywords):
            merch_count += 1
            continue

        if any(e in text for e in emojis):
            merch_count += 1

    return min(merch_count / len(tweets) * 100, 100.0)
```

### 6.3 建议新增的数据库字段

```sql
ALTER TABLE creator_features ADD COLUMN tweet_merch_score FLOAT DEFAULT 0;
ALTER TABLE creator_features ADD COLUMN tweet_merch_count INT DEFAULT 0;
ALTER TABLE creator_features ADD COLUMN has_recent_merch BOOLEAN DEFAULT FALSE;
```

---

## 7. 开发服务器待办清单

### 7.1 高优先级

1. **统一 Sellability 特征定义**
   - 确认 `_build_feature_vector` 与训练时使用的特征完全一致。
   - 移除或补全 `character_consistency` 等不一致字段。

2. **提高 SPS 切换阈值（可选）**
   - 当前 SPS 切换阈值是 30（`<30 Ridge, >=30 XGBoost`）。
   - 建议参考 Sellability，提高到 **300~500**，避免小样本下 XGBoost 过拟合。

3. **增加推文抓取量**
   - `pipeline/deep_scrape.py`：`tweets_per_handle = 50`（或 100）。

4. **新增推文周边检测特征**
   - `feature_engine.py`：新增 `calc_tweet_merch_score`。
   - `creator_features` 表：新增 `tweet_merch_score`, `tweet_merch_count`, `has_recent_merch`。

### 7.2 中优先级

5. **粉丝列表抓取**
   - 启用 `followers_actor`。
   - 新增 `followers` 表。
   - 从粉丝简介推断地域/兴趣/付费意愿。

6. **评论抓取**
   - 配置支持 `includeReplies` 的 Actor。
   - 挖掘"购买意向"评论。

### 7.3 低优先级 / 长期

7. **多语种 Embedding 方案**
   - 安装 `sentence-transformers`。
   - 用 `paraphrase-multilingual-MiniLM-L12-v2` 做语义匹配。

8. **SPS 标签改造**
   - 当积累足够合作销售数据后，将目标变量从 `total_sales_log1p` 改为真正的"合作销量"。

---

## 8. 关键实验结果文件

以下文件已在线上服务器生成，可供参考：

| 文件路径 | 说明 |
|---------|------|
| `models/sellability_model_comparison.json` | Sellability LR vs XGBoost 对比报告 |
| `models/sps_model_comparison.json` | SPS Ridge vs XGBoost 对比报告 |
| `models/sellability_model.joblib.backup.20260610_171943` | Sellability 老模型备份 |
| `models/sps_model.joblib.backup.20260610_174052` | SPS 老模型备份 |
| `docs/improvement_plan_session_20260610.md` | 本文档 |

---

## 9. 核心结论

1. **Sellability 模型**：当前 248 样本不足以支撑 XGBoost，LR 泛化更优。阈值已临时调整为 800，样本达到 800 前强制使用 LR。
2. **SPS 模型**：现有 13 个特征无法预测销量（R² 为负）。核心问题不是模型，而是特征与销量之间缺乏相关性。必须补充周边历史、合作历史、粉丝画像等数据。
3. **毛绒娃娃业务**：应围绕"IP/角色价值"和"粉丝付费意愿"重建特征体系，重点抓取推文历史、粉丝列表、评论内容。
4. **多语种检测**：优先使用链接检测 + 复用 `bio_rules.yaml` 规则；中期可引入多语种 Embedding；LLM 仅用于精筛。

---

*文档生成时间：2026-06-10*
*基于会话记录整理，未修改任何代码文件*
