# ECS + RDS 生产升级方案（核查用）

本文档用于将**已部署版本**从 Git 提交 **`b3b5f72f7ce39b3956400cd41b9a9ada4d199753`** 升级到**仓库当前推荐目标**（编写时 `HEAD` 为 **`4bfb801b81077b809b9f3ea24cf1e3dfa39d1841`**）。部署前请执行 `git rev-parse HEAD` 与远端 `git fetch && git log -1 origin/<主分支>` 核对，以**实际拉取后的提交**为准。

> 本次全量重置发布标记：**`20260411`**（对应脚本 `scripts/prod_full_reset_redeploy.sh` 内 `Release Mark: 20260411`）。

---

## 1. 升级范围摘要

| 维度 | 说明 |
|------|------|
| **上次线上代码（基准）** | `b3b5f72` |
| **目标代码（示例）** | `4bfb801`（或你 `git pull` 后的 `HEAD`） |
| **ECS** | 优先使用自动化脚本 `scripts/prod_full_reset_redeploy.sh`（交互确认）完成拉代码、清库重建、管理员创建、种子导入、重启与健康检查 |
| **RDS（本次业务约定）** | **清空原有业务数据**，**不做备份**，按 **`public` schema 删除并全量建表**（见第 3 节），与新版种子导入、创作者挖掘逻辑对齐；**不执行**历史回填脚本 `003`。 |
| **种子文件** | 放在**项目根目录下的 `data/`**（与仓库内 `data/README.md` 约定一致）。宿主机示例：`/opt/craftifyxminer/data/你的文件.xlsx`。`docker-compose.prod.yml` 已将 **`./data` 挂载为容器内 `/app/data`**（只读），导入命令使用 **`/app/data/...`** 路径。 |

相对 `b3b5f72`，仓库含大量业务、Dashboard、Pipeline、Docker 与数据库结构变更；**仅更新 ECS 不处理 RDS 会导致应用与库表不一致**。

---

## 2. 两条路径如何选择

| 路径 | 适用场景 |
|------|----------|
| **方案 A — 清空重建（本文主路径）** | **丢弃线上旧数据**，全量重来；**本次采用：不备份 RDS。** |
| **方案 B — 增量迁移** | **必须保留** RDS 内历史数据时，按 **`003`→`004`→`005`→`006`** 顺序执行（见第 8 节）。 |

---

## 3. 方案 A（主路径）— RDS 清空并重建

### 3.1 说明

- 脚本：`scripts/prod_rebuild_database.sh`
- 行为概要：停止相关容器 → **`DROP SCHEMA public CASCADE`**（需设置 `WIPE_PUBLIC_SCHEMA=yes`）→ 执行 **`db/schema.sql`** + **`db/indexes.sql`** + 迁移 **`004`～`006`**。
- **`003_backfill_discovery_source.sql` 不执行**（仅用于旧库回填）。
- **风险**：清空后**数据不可恢复**；**本次明确不做备份**，请确认团队已接受该风险。

### 3.2 前置：代码、`.env`、种子文件

1. 在 ECS 上进入项目目录（示例 **`/opt/craftifyxminer`**），确认 `.env` 可用且 `DATABASE_URL` 指向生产 RDS：

```bash
cd /opt/craftifyxminer
git status

# 对照仓库 .env.example 合并、填写生产 .env（勿用开发机整文件覆盖）
set -a && source .env && set +a
```

2. **种子文件**：放到 **`/opt/craftifyxminer/data/`**（即项目下 **`data/`** 目录）。`data/*` 通常不入 Git，需在服务器上**上传或 scp** 就位后再执行导入。

3. 确认 **`docker-compose.prod.yml`** 已包含 **`./data:/app/data:ro`**（当前仓库已配置）；若你本地分支较旧，请先 `git pull` 拿到该挂载再执行后续步骤。

2. **种子文件**：放到 **`/opt/craftifyxminer/data/`**（项目 `data/` 目录），例如：

```bash
ls /opt/craftifyxminer/data
```

3. 确认 **`docker-compose.prod.yml`** 包含 **`./data:/app/data:ro`**（当前仓库已配置）。

### 3.3 自动化执行（推荐）

新增脚本：`scripts/prod_full_reset_redeploy.sh`

- 交互确认内容包括：
  - 破坏性口令确认（`I_UNDERSTAND`）
  - 是否执行 `git fetch + git pull`
  - 全流程串行执行并在末尾做 `/health` 检查
- 实际执行内容：
  1) `git pull`（可选）  
  2) 调用 `scripts/prod_rebuild_database.sh` 清空并重建数据库  
  3) 创建管理员  
  4) 导入种子文件（`/app/data/...`）  
  5) `docker compose -f docker-compose.prod.yml up -d --build`  
  6) 健康检查

#### 交互模式（推荐）

```bash
cd /opt/craftifyxminer
bash scripts/prod_full_reset_redeploy.sh \
  --branch <主分支名> \
  --seed-file "data/创作者账号链接及销量收集.xlsx"
```

#### 非交互模式（CI/批处理）

```bash
bash scripts/prod_full_reset_redeploy.sh \
  --non-interactive \
  --branch <主分支名> \
  --seed-file "data/creators_seed_from_xlsx.csv" \
  --admin-username admin \
  --admin-password "<强密码>"
```

脚本支持 `--help` 查看全部参数（如 `--skip-git-pull`、`--skip-healthcheck`）。

---

## 4. 验证清单

- [ ] `docker compose -f docker-compose.prod.yml ps` 各服务 healthy / running  
- [ ] `curl -sf http://127.0.0.1/health`  
- [ ] 日志：`docker compose -f docker-compose.prod.yml logs --tail=200 server dashboard cron`  
- [ ] 浏览器登录 Dashboard，确认种子页、候选人、流水线相关功能  
- [ ] RDS：抽样 `creators` 等与种子导入结果一致  

---

## 5. 回滚思路

- **本次未做 RDS 备份**：无法通过快照恢复旧数据；仅可将应用代码 `git checkout` 到旧提交后重建镜像（**库结构可能与旧代码不匹配**，需谨慎）。若将来需要可恢复方案，应另行约定备份策略。

---

## 6. 阿里云侧核对项

- [ ] **安全组**：入方向 **22 / 80 / 443**（按策略收紧来源）。  
- [ ] **RDS 白名单**：包含 ECS 访问 RDS 所用 IP。  
- [ ] **出网**：Apify、LLM API 等可访问。  

---

## 7. 附录 — 脚本说明

| 脚本 | 说明 |
|------|------|
| `scripts/deploy.sh` | 新机一键装 Docker + 交互写 `.env` 等；不是本次「已有 ECS、清空 RDS」的主路径。 |
| `scripts/prod_full_reset_redeploy.sh` | **本次主入口**：交互确认 + 清库重建 + 管理员创建 + 种子导入 + 服务启动 + 健康检查。 |
| `scripts/prod_rebuild_database.sh` | **方案 A 核心**；`CONFIRM=yes`，清空库需 **`WIPE_PUBLIC_SCHEMA=yes`**。 |

---

## 8. 方案 B（备选）— 保留旧数据时的增量迁移

仅在**不能清空** RDS 时使用：按顺序执行 **`003` → `004` → `005` → `006`**。

```bash
set -a && source .env && set +a
export PGOPTIONS='-c statement_timeout=0'
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/003_backfill_discovery_source.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/004_sps_ml_refactor.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/005_seed_platform_account_unique.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/006_dual_model_scores.sql
```

迁移前可执行以下 SQL 预判 **`005`** 是否因重复用户失败：

```sql
SELECT lower(trim(username)) AS norm, COUNT(*) AS n
FROM creators
GROUP BY 1
HAVING COUNT(*) > 1;
```

---

## 9. 附录 — 变更文件速览（相对 `b3b5f72`）

以 `git diff b3b5f72..HEAD --stat` 为准做审计（编写时约 56 个文件）。

---

## 10. 核查签字（可选）

| 项目 | 执行人 | 日期 | 备注 |
|------|--------|------|------|
| 已确认**不备份** RDS | | | |
| 已采用方案 **A** 或 **B** | | | A：清空重建 |
| `prod_rebuild_database.sh` 成功（方案 A）或 `003`～`006` 成功（方案 B） | | | |
| 种子文件已放入 `data/` 并完成导入（方案 A） | | | |
| `.env` 已合并 | | | |
| `docker compose ... up -d --build` 成功 | | | |
| `/health` 与业务冒烟 | | | |

---

*文档随仓库发布；若采用 Tag/Release，可将「目标提交」改为发布 Tag 并替换文中 `4bfb801`。*
