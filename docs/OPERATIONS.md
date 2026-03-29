# CraftifyX Miner — 运维手册 v1.0

> 适用版本：7.0+｜最后更新：2026-03-29

---

## 目录

1. [架构总览](#1-架构总览)
2. [容器与服务](#2-容器与服务)
3. [日志体系](#3-日志体系)
4. [流水线运行](#4-流水线运行)
5. [日常监控](#5-日常监控)
6. [常见排障](#6-常见排障)
7. [备份与恢复](#7-备份与恢复)

---

## 1. 架构总览

生产环境使用 `docker-compose.prod.yml`，包含以下服务：

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

所有容器共享 `.env` 环境变量，通过 `env_file: .env` 注入。

---

## 2. 容器与服务

| 容器 | 镜像 / 入口 | 职责 | 健康检查 |
|------|-------------|------|----------|
| `nginx` | `nginx:alpine` | 反向代理、限流、静态缓存 | 依赖 server + dashboard healthy |
| `server` | `gunicorn server.app:app` | Flask API、Webhook、健康端点 | `GET /health` 每 30s |
| `dashboard` | `streamlit run dashboard/app.py` | 可视化仪表盘 | `GET /_stcore/health` 每 30s |
| `cron` | `python cron/daily_job.py` | 定时流水线 + 日报汇总 | 无（看容器 Up 状态） |

### 常用命令

```bash
cd /opt/craftifyxminer

# 查看所有容器状态
docker compose -f docker-compose.prod.yml ps

# 重启所有服务（不重建镜像）
docker compose -f docker-compose.prod.yml restart

# 拉新代码后重建镜像并重启
git pull
docker compose -f docker-compose.prod.yml up -d --build --force-recreate

# 停止所有服务
docker compose -f docker-compose.prod.yml down
```

---

## 3. 日志体系

### 3.1 日志来源与位置

| 来源 | 输出目标 | 路径 / 查看方式 |
|------|---------|----------------|
| Nginx access/error | 文件 | Docker 卷 `nginx_logs` → `/var/log/nginx/` |
| Gunicorn access | 文件 | Docker 卷 `app_logs` → `/app/logs/gunicorn-access.log` |
| Gunicorn error | 文件 | Docker 卷 `app_logs` → `/app/logs/gunicorn-error.log` |
| Flask 应用 | 文件 + stdout | `/app/logs/flask.log`（RotatingFileHandler, 10MB x 5）+ Docker 日志 |
| Cron 定时任务 | stdout | Docker 日志（`docker compose logs cron`） |
| Pipeline runner | stdout | Docker 日志（print 输出，面向手动执行与 cron） |
| Dashboard (Streamlit) | stdout | Docker 日志（`docker compose logs dashboard`） |

### 3.2 日志格式

所有 Python `logging` 输出统一格式：

```
%(asctime)s %(name)s %(levelname)s %(message)s
```

示例：

```
2026-03-29 08:00:05,123 pipeline.discovery INFO Generated 20 anchors (16 regular + 4 explore)
2026-03-29 08:01:12,456 pipeline.ai_filter WARNING Provider dashscope auth denied (HTTP 401), trying next: ...
2026-03-29 08:05:30,789 pipeline.runner INFO Pipeline complete: SUCCESS in 330.5s
```

### 3.3 Logger 清单

| Logger 名 | 模块 | 关键日志 | 级别 |
|-----------|------|---------|------|
| `pipeline.runner` | 全链路运行器 | 开始/每步计时/汇总 | INFO |
| `pipeline.discovery` | 锚点与 L1 | 锚点数量、Apify run ID | INFO |
| `pipeline.intake` | 数据入库 | 入库/过滤统计 | INFO |
| `pipeline.ai_filter` | LLM Bio 过滤 | 调用失败/重试/provider 切换、JSON 解析 | WARNING / ERROR |
| `pipeline.deep_scrape` | 深度抓取 | 抓取人数、预算检查 | INFO / WARNING |
| `pipeline.feature_engine` | 特征计算 | 计算数量 | INFO |
| `pipeline.sps_scorer` | SPS 评分 | 评分数量 | INFO |
| `pipeline.evolution` | 种子晋升 | 晋升数量 | INFO |
| `cron.daily_job` | 定时调度 | 任务开始/完成 | INFO |
| `server.app` | Flask 主应用 | 未捕获异常 | ERROR |
| `server.webhook` | Apify 回调 | 回调处理 | INFO |
| `db.connection` | 数据库连接 | 连接详情 | DEBUG |

### 3.4 Docker 卷说明

生产 compose 中定义了两个命名卷：

| 卷名 | 挂载容器 | 容器路径 | 内容 |
|------|---------|---------|------|
| `app_logs` | server, dashboard, cron | `/app/logs` | flask.log, gunicorn-*.log |
| `nginx_logs` | nginx | `/var/log/nginx` | access.log, error.log |

查看卷在宿主机的物理路径：

```bash
docker volume inspect craftifyxminer_app_logs | grep Mountpoint
docker volume inspect craftifyxminer_nginx_logs | grep Mountpoint
```

---

## 4. 流水线运行

### 4.1 定时任务调度

| 时间 (Asia/Shanghai) | Job ID | 执行内容 |
|---------------------|--------|---------|
| **08:00** | `daily_pipeline` | 全链路：锚点 → L1 扫描 → 深度抓取 → 特征 → SPS |
| **23:00** | `daily_summary` | 日报统计 + 成本核算 + 种子晋升 |

### 4.2 全链路流程（`pipeline.runner`）

```
[1/5] Generate anchors     — 从种子库选取锚点 + 探索策略
[2/5] L1 scan              — Apify Following Actor 扫描 + 入库 + 规则/AI 过滤
[3/5] Deep scrape          — Apify 深度抓取候选人 Profile + Tweets
[4/5] Feature computation  — 计算 10 维特征指标
[5/5] SPS scoring          — 计算 SPS 综合评分 + 中心度分类
```

每步计时，异常时标记 FAILED 并继续后续步骤。结束后输出汇总表。

### 4.3 手动执行

```bash
# 全量链路（使用默认参数）
docker compose -f docker-compose.prod.yml run --rm \
  -v /opt/craftifyxminer/data:/app/data \
  server python -m pipeline.runner

# 小批次冒烟测试
docker compose -f docker-compose.prod.yml run --rm \
  server python scripts/quick_smoke_pipeline.py \
  --anchors 1 --max-following 30 --deep-limit 3
```

### 4.4 输出示例

```
============================================================
 CraftifyX Miner — Daily Pipeline
 Date: 2026-03-29 14:30:05
============================================================
 Tasks:
  [1/5] Generate anchors
  [2/5] L1 scan (Apify following)
  [3/5] Deep scrape
  [4/5] Feature computation
  [5/5] SPS scoring
============================================================

[1/5] Generate anchors ...
  -> 20 anchors (16 seed + 4 explore)                3.2s

[2/5] L1 scan (Apify following) ...
  -> stored 500, passed 27+67 / rejected 2+38 / grey 105   42.1s

[3/5] Deep scrape ...
  -> 50 candidates, run_id=abc123def                  68.5s

[4/5] Feature computation ...
  -> 26 creators computed                             1.8s

[5/5] SPS scoring ...
  -> 26 creators scored                               0.9s

============================================================
 Summary
------------------------------------------------------------
 Anchors generated:   20
 L1 stored:           500 (passed 27+67, rejected 2+38)
 Deep scraped:        50
 Features computed:   26
 Scores computed:     26
 Total elapsed:       116.5s
 Status:              SUCCESS
============================================================
```

---

## 5. 日常监控

### 5.1 容器健康

```bash
# 所有容器状态一览
docker compose -f docker-compose.prod.yml ps

# 预期输出：nginx / server / dashboard 为 healthy，cron 为 Up
```

### 5.2 查看 cron 流水线日志

```bash
# 实时跟踪（Ctrl+C 退出）
docker compose -f docker-compose.prod.yml logs -f cron

# 搜索今天是否执行过全链路
docker compose -f docker-compose.prod.yml logs cron | grep "Daily Pipeline"

# 搜索完成状态
docker compose -f docker-compose.prod.yml logs cron | grep "Pipeline complete"
```

### 5.3 查看 Flask / Gunicorn 日志

```bash
# 列出日志文件
docker compose -f docker-compose.prod.yml exec server ls -lh /app/logs/

# Flask 应用日志（最近 100 行）
docker compose -f docker-compose.prod.yml exec server tail -100 /app/logs/flask.log

# Gunicorn 访问日志
docker compose -f docker-compose.prod.yml exec server tail -50 /app/logs/gunicorn-access.log

# Gunicorn 错误日志
docker compose -f docker-compose.prod.yml exec server tail -50 /app/logs/gunicorn-error.log
```

### 5.4 查看 Nginx 日志

```bash
docker compose -f docker-compose.prod.yml exec nginx tail -50 /var/log/nginx/access.log
docker compose -f docker-compose.prod.yml exec nginx tail -50 /var/log/nginx/error.log
```

### 5.5 Dashboard 成本监控

浏览器访问 `http://<ECS-IP>/`，进入 **Cost Monitor** 页面，查看：
- 当日 Apify / LLM 费用
- 月累计费用与预算使用率
- 超阈值时页面会显示告警

### 5.6 验证 LLM 配置

```bash
docker compose -f docker-compose.prod.yml run --rm server python -c "
from pipeline.ai_filter import _is_non_retryable_auth_error
print('Code version: OK')
from config.settings import FALLBACK_CHAIN, PROVIDER_CONFIGS, PROVIDER_MODELS
print('FALLBACK_CHAIN:', FALLBACK_CHAIN)
for p in FALLBACK_CHAIN:
    cfg = PROVIDER_CONFIGS.get(p, {})
    key = cfg.get('api_key', '')
    masked = key[:6] + '...' + key[-4:] if len(key) > 10 else '(empty)'
    print(f'  {p}: model={PROVIDER_MODELS.get(p)}, key={masked}, base_url={cfg.get(\"base_url\")}')
"
```

---

## 6. 常见排障

### 6.1 LLM 调用报 401 / Provider 不断重试

| 症状 | 日志关键词 | 排查 |
|------|-----------|------|
| 反复 `Retrying in 1s/2s/4s` | `Provider xxx attempt N failed` | **旧代码**未更新；执行 `git pull && docker compose up -d --build` |
| `auth denied, trying next` 后仍 `All providers failed` | `All providers failed` | `FALLBACK_CHAIN` 中所有 provider 的 key 均无效；核查 `.env` 中各 `*_API_KEY` |
| 只想用 Kimi，但仍调用 dashscope | `Provider dashscope` | `.env` 中设 `LLM_FALLBACK_CHAIN=moonshot` 并重建容器 |

### 6.2 LLM 返回 JSON 解析失败

| 症状 | 原因 | 处理 |
|------|------|------|
| `Failed to parse LLM response as JSON` + 截断内容 | `LLM_MAX_TOKENS` 太小 | `.env` 中设 `LLM_MAX_TOKENS=16384` |
| `Salvaged N objects from truncated` | 截断但已部分抢救 | 正常降级，不影响后续步骤 |

### 6.3 容器状态异常

```bash
# 查看容器退出原因
docker compose -f docker-compose.prod.yml logs --tail=50 <container_name>

# 强制重建
docker compose -f docker-compose.prod.yml up -d --build --force-recreate
```

### 6.4 `.env` 改了但没生效

`docker compose restart` **不会** 重新读取 `.env`。必须：

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate
```

若同时改了代码，需加 `--build`。

### 6.5 Apify 预算用完

日志中出现 `Daily Apify budget exhausted`，当日不再触发新的抓取 run。次日自动恢复。
如需临时提额，修改 `.env` 中 `DAILY_APIFY_BUDGET_USD` 并重建容器。

---

## 7. 备份与恢复

### 7.1 数据库

生产使用阿里云 RDS，备份由 RDS 自动管理。手动备份：

```bash
# 导出
docker compose -f docker-compose.prod.yml exec server \
  pg_dump "$DATABASE_URL" > backup_$(date +%Y%m%d).sql

# 恢复
psql "$DATABASE_URL" < backup_20260329.sql
```

### 7.2 日志卷

日志卷为 Docker 命名卷，随 `docker compose down` 保留（除非加 `-v`）。
如需归档：

```bash
# 复制到宿主机
docker cp $(docker compose -f docker-compose.prod.yml ps -q server):/app/logs ./logs_backup_$(date +%Y%m%d)
```

---

*本文档随项目迭代更新，如有疑问请联系项目维护者。*
