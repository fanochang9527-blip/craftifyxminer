# CraftifyX Miner 6.0 文档摘要

> **完整本地版（含文首「作用与核心内容」）**：[CraftifyX-Miner-6.0.md](./CraftifyX-Miner-6.0.md)  
> 原文：[CraftifyX Miner 6.0 - 全栈创作者发现与进化系统](https://hlso6imk735ho.ok.kimi.link)

## 1. 定位与概览

**CraftifyX Miner 6.0** 是一套端到端的「创作者发现 + 评分分层 + BD 决策 + 数据驱动进化」系统：从多源种子与图谱扩展发现候选人，经 Apify 采集与 10 维特征计算，输出 SPS 评分与联系概率，支撑 BD 工作台与月度模型/权重校准。

文档中展示的运营量级（示例）：日发现约 **687** 人、候选池约 **15,847**、示例月度 GMV **$284K**、系统版本 **v6.0**。

---

## 2. 四层架构 + 双轨进化

| 层级 | 名称 | 要点 |
|------|------|------|
| 输入层 | 多源发现引擎 | 种子导入（100+ 销售验证创作者）、每日 Multi-hop（Layer-1/2 + 反向）、动态锚点 **60% 利用 + 40% 探索** |
| 处理层 | 智能计算引擎 | Apify **4 类**采集（Profile / Tweets / Interaction / Followers）、**10 维指标**、轻量中心度（Hub/Connector/Peripheral）、**SPS** + **Contact Probability** |
| 应用层 | BD 决策引擎 | 分级候选池（Hub 优先 + SPS 排序）、BD Dashboard（Interested / Rejected / Deferred）、联系执行与结果追踪 |
| 进化层 | 双轨飞轮 | Track1：BD 反馈优化联系模型；Track2：Sales/GMV 驱动 XGBoost 权重；新 Seed 晋升（如 GMV>$1000）；月度重训练 |

**双轨机制简述**

- **Track 1**：用 outreach 结果（如是否回复）训练逻辑回归等模型，更新 Contact Probability（文档称准确度目标约 **82%**）。
- **Track 2**：按创作者类型用 XGBoost 拟合 GMV 等目标，用特征重要性更新 SPS 权重。

---

## 3. 业务流程（种子 → 飞轮）

1. **P1 种子导入（约 Week 1）**：`merged_creators.csv` 入库；按销售额打 `seed_tier`（示例：S/A/B/C 人数分布）。
2. **P2 初始 Graph（约 Week 2）**：约 100 个 Seed，每人约 500 Following，形成约 **5,000** Layer-1 候选人、约 **5 万** 关系边。
3. **P3 每日 Multi-hop**：合计约 **500–800 人/日**；预算 **60% / 30% / 10%** 分给 Layer-1、Layer-2、反向挖掘（见下节）。
4. **P4 指标与中心度**：采集 → 特征 → 中心度 → SPS，流程自动化。
5. **P5 BD 流程**：早日报 → 上午人工判定（文档示例日审 **20–30** 人）→ 下午执行联系。
6. **P6 月度进化**：联系模型更新、SPS 校准、新 Seed 晋升规则跑通。

---

## 4. Multi-hop 发现策略与预算

| 通道 | 预算 | 机制摘要 | 文档中的产出量级 |
|------|------|----------|------------------|
| **Layer-1** | 60% | 每日动态锚点（高 GMV Seed + 高 SPS 未成交探索），每人抓约 500 Following；约 20 锚点/日 | 约 **300–400** 人/日，成本约 **$6/日** |
| **Layer-2** | 30% | 「超级连接器」：被 **≥3** 个 Seed 关注的账号，每人约 200 Following | 约 **100–150** 人/日，约 **$3/日** |
| **反向** | 10% | Tier S 粉丝抓取，Bio/粉丝区间过滤；每周约 2 次 | 约 **50–100** 人/次，约 **$2/日** |

**日汇总**：约 **500–800** 人产出，总成本约 **$10–15/日**（文档口径）。

---

## 5. 轻量中心度与 BD 优先级

**定义**（基于「有多少个 Seed 关注该创作者」，避免重图算法）：

- **Hub**：被 **≥5** 个 Seed 关注 — BD 最优先。
- **Connector**：**2–4** 个 — 次级优先，有潜力成 Hub。
- **Peripheral**：**0–1** 个 — 依赖 SPS。

文档示例候选池分布：**15 Hub / 127 Connector / 15,705 Peripheral**。

**排序策略（摘要）**

1. Hub 且 SPS>**80**  
2. Connector 且 SPS>**75**  
3. Peripheral 且 SPS>**75**

---

## 6. 10 维指标（名称与计算思路）

文档给出雷达对比维度（OC、Vtuber、Fan Artist 等）及公式要点：

| 维度 | 含义 | 计算要点（文档） |
|------|------|------------------|
| Audience | 规模 | `log10(followers+1)×20` |
| Engagement | 粘性 | `(赞+转×2+评×3)/followers×100` |
| Virality | 爆款 | top3 均值 / 月均值，>5x → 100 |
| Posting | 勤勉 | 月发帖数/30×100 |
| Monetization | 变现 | Bio 关键词：商店 90 / 接单 60 / 无 0 |
| Growth | 增速 | 月环比粉丝增长 |
| Circle Influence Score | 圈层影响力（Miner 7.0） | 被多少个 Seed 关注（`seed_connections`）归一化到 0–100，如 `min(100, seed_connections×20)` |
| Character Consistency | IP 化 | pHash 最大聚类/总图片×100 |
| Community | 社区 | `(mentions×2+fanart×5)` 标准化 |
| Data Confidence | 置信 | 账号年龄×0.6 + 完整度×0.4 |

---

## 7. BD 工作台（文档示例）

- 今日日报：新候选 **687**；Hub 高优 **15**；Connector **42**；SPS>**75** 共 **68**。  
- 本周追踪示例：Interested **15**、Contacted **8**、Responded **5**。  
- 进化洞察示例：Contact Probability 准确度 **78%**（目标 >75%）；权重建议如 **CharacterConsistency 提至 0.25**。

---

## 8. 数据模型与规模

**7 张核心表**：`creators`、`tweets`、`creator_features`、`creator_graph`、`creator_scores`、`sales_feedback`、`outreach_log`（字段见原文档）。

**规模预估**：creators **~5 万**、tweets **~250 万**、graph **~50 万**边、`sales_feedback` **~1000/年**。

---

## 9. 代码与目录（文档示意）

```
project/
├── config/          # apify_config.yaml, weights.yaml
├── pipeline/        # seed_import, initial_graph, daily_discovery, feature_engine, evolution
├── dashboard/       # app.py（Streamlit）
├── models/          # contact_predictor.pkl, sps_weights.json
└── cron/            # daily_job.py
```

---

## 10. 六周落地路线（摘要）

| 周次 | 主题 | 交付要点 |
|------|------|----------|
| W1 | 种子导入 | PostgreSQL、CSV 导入、Tier 标记 |
| W2 | 初始 Graph | Apify 4 Actor、Seed Following、Layer-1 |
| W3 | 指标 | Feature Engine、Seed 10 维、初始 SPS 权重 |
| W4 | Dashboard | Streamlit、BD 流程、`outreach_log` |
| W5 | 日更发现 | Multi-hop 自动化、动态锚点、Layer-2 |
| W6 | 飞轮 | 销售数据录入、首次权重校准、新 Seed 晋升测试 |

---

## 11. 成本与 ROI（文档口径）

- **月度成本**约 **$414**（Apify **$49** + 采集 **$300** + 其他 **$65**）。  
- **月发现量**约 **15,000**（500 人/日×30）。  
- **预计成交** **15–30** 人（10–20% 转化假设）。  
- **月度 GMV 增量** **$75K–$150K**；系统成本占 GMV 约 **0.5%**（文档示例）。

---

## 12. 小结

该文档描述的是一套**可落地的创作者增长与 BD 运营系统**：以种子与关注关系图为扩展基础，用**预算化 Multi-hop**控制发现广度与成本，用**轻量中心度 + SPS**做排序，用**BD 与成交双反馈**闭环迭代模型与权重。实施上按 **6 周**从数据与图谱铺到日更发现与飞轮。

如需与实现对照，请以仓库内实际代码与配置为准；本文为对公开说明页的**结构化解构摘要**，非产品承诺或合同指标。
