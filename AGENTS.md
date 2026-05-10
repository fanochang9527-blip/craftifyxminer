# CraftifyX Miner — Agent 开发规范

> 本文件面向代码贡献者与自动化 Agent，约定 Git 工作流、代码风格、提交规范与部署流程。

---

## 1. Git 工作流（Feature Branch Workflow）

### 1.1 核心原则

- **`main` 分支始终保持可部署状态**，禁止直接向 `main` 推送未经审查的代码。
- 所有功能开发、Bug 修复、配置变更必须在**独立分支**上进行。
- 修改完成后通过 **Pull Request**（或本地合并）回并到 `main`。

### 1.2 分支命名规范

| 类型 | 命名格式 | 示例 |
|------|---------|------|
| 功能开发 | `feature/<简短描述>` | `feature/daily-consumption-priority` |
| Bug 修复 | `fix/<bug描述>` | `fix/discovery-batch-count-bug` |
| 紧急热修 | `hotfix/<问题描述>` | `hotfix/apify-timeout-retry` |
| 文档更新 | `docs/<主题>` | `docs/deployment-guide-v2` |

### 1.3 标准开发流程

```bash
# 1. 基于最新 main 创建分支
git checkout main
git pull origin main
git checkout -b feature/xxx

# 2. 开发、测试、提交
# ... coding ...
pytest tests/ -q

# 3. 提交并推送分支
git add .
git commit -m "feat: xxx"
git push origin feature/xxx

# 4. 合并回 main（本地或 GitHub PR）
git checkout main
git merge feature/xxx --no-ff
git push origin main

# 5. 清理
git branch -d feature/xxx
git push origin --delete feature/xxx
```

---

## 2. Commit Message 规范

采用 **`<type>: <subject>`** 格式，subject 使用中文或英文均可，但需在同一仓库内保持一致。

| Type | 含义 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构（不改变外部行为） |
| `docs` | 文档更新 |
| `chore` | 构建、工具、配置变更 |
| `test` | 测试相关 |

### 示例

```
feat: 深度抓取按当天优先排序，避免 backlog 无限积压
fix: 修复 discovery_batches raw_discovered 不回写的问题
chore: 上调默认 DEEP_SCRAPE_BATCH_SIZE 至 300、预算至 40 USD
docs: 补充 ECS-RDS 生产升级方案
```

---

## 3. 代码提交前检查清单（Pre-commit Checklist）

每位贡献者在提交前必须确认：

- [ ] **测试通过**：`pytest tests/ -q` 全部通过，无新增失败。
- [ ] **敏感信息未泄露**：`.env`、API Key、数据库密码、JWT Secret 未出现在 diff 中。
- [ ] **环境变量同步**：如新增/修改了环境变量，`config/settings.py` 与 `.env.example` 已同步更新。
- [ ] **数据库变更可追溯**：
  - 新增表/字段 → 更新 `db/schema.sql`
  - 增量变更 → 在 `db/migrations/` 新增 `00X_description.sql`
- [ ] **日志与监控**：关键业务流程变更后，检查日志输出是否有助于排查问题。
- [ ] **Docker 可构建**：生产配置变更后，确认 `docker compose -f docker-compose.prod.yml build` 无错误。

---

## 4. 敏感信息保护

| 文件类型 | 处理方式 |
|---------|---------|
| `.env`（API Key、密码） | `.gitignore` 排除，仅提供 `.env.example` 模板 |
| `data/*.csv` / `*.xlsx` | `.gitignore` 排除，通过安全渠道传递 |
| `models/*.joblib` / `*.pkl` / `*.json` | `.gitignore` 排除，冷启动后可训练生成 |
| `*.log` | `.gitignore` 排除 |

**红线**：任何包含真实 API Key、数据库密码、JWT Secret 的文件**不得**进入 Git 历史。如误提交，需立即轮换密钥并使用 `git filter-repo` 清理历史。

---

## 5. 项目结构与编码约定

### 5.1 Python 风格

- 遵循 **PEP 8**，使用 4 空格缩进。
- 类型注解：公共函数参数与返回值尽可能标注类型（`list[dict] | None` 等）。
- 日志：使用 `logging.getLogger(__name__)`，禁止裸 `print` 输出业务日志（CLI 工具除外）。
- 异步：LLM 调用等 IO 密集型操作优先使用 `asyncio` + `AsyncOpenAI`。

### 5.2 配置管理

- 所有可变配置通过**环境变量**注入，`config/settings.py` 统一读取。
- 禁止在代码中硬编码密钥、密码、URL。
- 成本敏感参数（预算、批次大小）必须在 `.env` 中可调，并附带合理默认值。

### 5.3 数据库约定

- 表名：小写下划线（`creator_scores`）
- 时间字段：使用 `TIMESTAMP DEFAULT NOW()`
- 布尔字段：使用 `BOOLEAN`，禁止用 `0/1` 字符串
- 外键约束：核心表必须建立外键，但大批量导入时可临时禁用以提升性能

---

## 6. 部署与发布流程

### 6.1 本地开发

```bash
docker compose up -d
pytest tests/ -q
```

### 6.2 生产部署（阿里云 ECS + RDS）

1. 合并代码到 `main`
2. 在 ECS 上 `git pull`
3. 核对 `.env` 配置
4. 如需数据库重建 → 运行 `scripts/prod_full_reset_redeploy.sh`
5. 如仅需代码更新 → `docker compose -f docker-compose.prod.yml up -d --build`
6. 验证：`curl http://<ECS_IP>/health`

### 6.3 版本标记

重大里程碑或生产稳定版本使用 Git Tag：

```bash
git tag -a v7.0.1 -m "v7.0.1: 深度抓取优化 + 消费率预警"
git push origin v7.0.1
```

---

## 7. Agent 特别约定

- Agent 修改代码后**必须**运行测试，禁止仅通过人工阅读判断正确性。
- Agent 修改环境变量或配置后**必须**同步更新 `.env.example` 与相关文档。
- Agent 新增数据库表或字段后**必须**更新 `db/schema.sql`，并考虑是否需要迁移脚本。
- Agent 使用 `StrReplaceFile` 等工具时，需确认替换目标在文件中唯一，避免误改。
