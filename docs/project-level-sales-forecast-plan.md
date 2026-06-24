# 项目级销量预测开发计划

> 生成时间：2026-06-22
> 状态：待用户确认关键问题 + 等待数据文件
> 本文件保存当前已确认的开发思路和后续实施计划，断网后可离线阅读。

---

## 一、背景与目标

### 1.1 现状

当前 CraftifyX Miner 的销量预测粒度是**创作者级**：

- `creators` 表聚合了 `total_sales` 和 `sales_transaction_count`
- `seed_import.py` 导入 `seed_file.csv` 时，按 `(platform, platform_account_id)` 去重，一个作者只保留一行
- `pipeline/sps_model.py` 训练目标为 `y = log1p(creators.total_sales)`
- `creator_scores` 一行对应一个创作者

### 1.2 问题

业务上的种子数据实际上是**合作记录级**：同一个作者可能合作过多次，每次合作都是一个独立项目，有独立的销量、SKU、品类等信息。创作者级预测会丢失“单次合作项目”的异质性。

### 1.3 目标

将销量预测的最小颗粒度从**创作者级**下沉到**项目/合作级**，模型训练目标改为预测**单次合作项目的销量**。

---

## 二、已确认的设计思路

1. **新建项目表**（待定名 `projects` 或 `creator_collaborations`）
   - 主键为项目唯一编号（业务侧项目编码）
   - 包含项目本身的字段
   - 包含该项目的作者信息（可含部分快照字段，减少 join）
   - 外键关联 `creators(id)`
   - 保留 `sku` 字段，与项目 ID 形成内外映射

2. **保留 `creators` 作为主档案**
   - 作者的基础资料、BD 状态、DNA 分析结果仍存于此
   - 不再以创作者级 `total_sales` 作为训练目标

3. **`seed_file.csv` 是项目级数据**
   - 每行 = 一个合作项目
   - `total_sales` 是**该项目的单次销售额**
   - 同一作者多行 = 该作者有多个合作项目

4. **项目具有自身特征**
   - 预测需结合**项目特征** + **作者特征**
   - 项目特征稍后补充（如价格、品类等）
   - 作者特征继续使用 DNA 相关特征作为输入

5. **模型训练目标改为项目级销量**
   - 训练样本数 = 项目数
   - 目标变量 = `projects.total_sales`
   - 输入特征 = 项目特征 + 作者特征

6. **评分表不项目化，前端工作台暂时不改**
   - 现有 `creator_scores` 表保持原样
   - 项目级预测结果需要另外的存储方案

7. **DNA 模型不再做创作者级销量预测**
   - DNA 特征的本意是服务于项目级预测
   - 作者级 DNA 分析继续保留，作为项目级模型的作者侧特征

8. **`seed_working.xlsx` 不作为训练样本**
   - 它代表“正在合作的创作者”，没有销量数据
   - 可作为模型**推理/预测**使用，但不进入训练集

9. **外部系统对接**
   - 项目内部使用自己的项目唯一编码
   - 同时保留 `sku` 字段用于与外部系统对应
   - 有一张外部表记录 sku ↔ 项目信息，稍后传入

10. **当前阶段仅确认思路，等待文件后再实施**
    - 用户准备好 `seed_file.csv`、sku 映射表、项目特征字段后再动手开发

---

## 三、待确认的关键问题

### A. 项目级预测结果的存储位置

用户要求“评分表不进行项目化”，但项目级预测结果必须落库。建议方案：

- **方案 1（推荐）**：新增 `project_scores` 表，一行一个项目的预测结果，与 `creator_scores` 并存
- **方案 2**：扩展 `creator_scores` 增加 `project_id` 列（但这会让表项目化，与要求冲突）

**待用户确认。**

### B. 项目表主键来源

项目唯一编号：

- 是外部系统已有的业务编码，直接随 `seed_file.csv` 导入？
- 还是由本系统生成，外部 `sku` 作为映射？

**待用户确认。**

### C. `seed_working.xlsx` 的项目编码

该文件只有作者名、没有销量。模型推理时：

- 是否给这些“正在合作”的作者生成项目记录？
- 如果需要项目级推理，项目 ID / SKU 从哪里来？
- 还是仅输出作者级预测到 `creator_scores`（维持现有逻辑）？

**待用户确认。**

### D. 外部 SKU 映射表

- 是用户直接提供 SQL/CSV，还是由开发方先按给定字段建表？
- 该表是否也作为项目特征的来源之一？

**待用户确认。**

### E. 现有 `creators.total_sales` 的处理

项目化后，`creators.total_sales` 可能失去单一语义：

- 保留为历史字段但逐步弃用？
- 改写成 `SUM(projects.total_sales)` 的视图或触发器？
- 项目导入后回写 `creators.total_sales` 以保持旧模型兼容？

**待用户确认。**

### F. 现有模型文件的处理

项目级模型：

- 作为新模型（如 `sps_model_project.joblib`）新增？
- 还是直接替换现有的 `sps_model.joblib` / `sps_model_dna.joblib`？

**建议新增独立模型文件**，避免破坏现有 `creator_scores` 推理链路。

**待用户确认。**

---

## 四、数据模型设计（草案）

### 4.1 项目表（`projects` / `creator_collaborations`）

```sql
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,           -- 项目唯一编号（业务侧编码）
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
    sku TEXT,                              -- 外部 SKU，用于外部系统对接
    project_name TEXT,                     -- 项目名称（可选）
    category TEXT,                         -- 项目品类/分类
    project_price FLOAT,                   -- 项目单价（用户稍后补充的项目特征示例）
    total_sales FLOAT,                     -- 该项目实际销售额（训练目标 y）
    transaction_count INTEGER,             -- 成交笔数
    launch_date DATE,                      -- 上架/合作日期
    source_file TEXT,                      -- 数据来源文件
    -- 作者快照字段（可选，减少 join）
    author_followers INTEGER,
    author_following INTEGER,
    author_account_age_days INTEGER,
    -- 元数据
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_projects_creator_id ON projects (creator_id);
CREATE INDEX idx_projects_sku ON projects (sku);
```

> 字段会根据用户最终提供的项目特征字段和 SKU 映射表调整。

### 4.2 项目评分表（`project_scores`，可选）

若采用方案 1，新增此表：

```sql
CREATE TABLE project_scores (
    id SERIAL PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id) ON DELETE CASCADE,
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
    creator_type VARCHAR(20),
    predicted_sales FLOAT,                 -- 项目级预测销量
    sps_score FLOAT,                       -- 映射后的 SPS 评分
    confidence FLOAT,
    contact_probability FLOAT,
    predicted_response_rate FLOAT,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(project_id)
);
```

### 4.3 外部 SKU 映射表

待定结构，等用户传入。

---

## 五、改造范围

### 5.1 数据库层

- 新增 `projects` 表
- 新增 `project_scores` 表（若确认）
- 新增外部 SKU 映射表（若确认）
- 更新 `db/schema.sql`
- 在 `db/migrations/` 下新增迁移脚本

### 5.2 数据导入层

- 改造 `pipeline/seed_import.py`
  - 不再按作者聚合
  - 先 upsert `creators`
  - 再逐行写入 `projects`
  - 标记 `is_seed = true`
- `seed_working.xlsx` 逻辑保持或微调（仅推理用）

### 5.3 特征工程层

- 项目特征 + 作者特征拼接
- 从 `creator_features` 读取作者级特征
- 从 `projects` 读取项目级特征
- 必要时新增 `project_features` 表缓存拼接后的特征向量

### 5.4 模型层

- 新增 `pipeline/project_sps_model.py`
  - 训练目标：`projects.total_sales`
  - 特征：项目特征 + 作者特征（含 DNA）
  - 模型文件：`models/sps_model_project.joblib`
  - Meta 文件：`models/sps_model_project_meta.json`
- 新增/更新预测函数：`predict_project_sales()` 等

### 5.5 评分层

- 新增项目级评分入口
- 结果写入 `project_scores`
- `creator_scores` 保持原样

### 5.6 测试层

- 新增 `tests/test_project_sales_model.py`
- 新增 `tests/test_seed_import_projects.py`
- 确保现有 `tests/test_sps_model.py`、`tests/test_creator_dna.py` 不受影响

### 5.7 配置层

- 更新 `.env.example`：新增项目级模型开关、路径等
- 更新 `config/settings.py`

---

## 六、实施步骤（待启动后执行）

1. **建分支**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/project-level-sales-forecast
   ```

2. **设计确认**
   - 与用户确认 A–F 关键问题
   - 确认项目表命名、字段
   - 拿到 `seed_file.csv`、sku 映射表、项目特征字段

3. **数据库迁移**
   - 编写 `db/migrations/023_add_projects_table.sql`
   - 更新 `db/schema.sql`

4. **改造导入流程**
   - 修改 `pipeline/seed_import.py`，支持项目级导入
   - 增加幂等性：同一 `project_id` 重复导入时更新

5. **特征拼接**
   - 新增 `pipeline/project_features.py`
   - 实现项目特征 + 作者特征拼接

6. **项目级模型**
   - 新增 `pipeline/project_sps_model.py`
   - 训练/预测项目级销量
   - 保存模型和 meta

7. **项目级评分**
   - 新增 `pipeline/project_scorer.py`
   - 将结果写入 `project_scores`

8. **测试**
   - 编写单元测试和集成测试
   - 跑 `pytest tests/ -q`，确保全部通过

9. **文档与配置同步**
   - 更新 `.env.example`
   - 更新 `config/settings.py`
   - 更新本计划文件

10. **提交分支（需用户许可）**
    ```bash
    git add .
    git commit -m "feat: 项目级销量预测"
    git push origin feature/project-level-sales-forecast
    ```

---

## 七、需要用户准备的材料

1. `seed_file.csv` 实际样例或完整列名
2. 外部 SKU/项目映射表结构和数据
3. 项目级特征字段列表及数据类型
4. 项目表命名偏好（`projects` vs `creator_collaborations`）
5. 对上述 A–F 问题的确认答复

---

## 八、后续约定

- 用户准备好上述材料后，发送给 Agent
- Agent 按本计划第 6 节步骤实施
- 所有代码修改在独立分支 `feature/project-level-sales-forecast` 进行
- 提交和合并前必须获得用户明确许可
