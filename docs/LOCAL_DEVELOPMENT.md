# 本地开发测试操作手册（Docker PostgreSQL + pytest + CSV + Dashboard）

适用于：**首次在本地验证代码**，数据库用 Docker 启动 PostgreSQL，应用用本机 Python 进程运行（便于断点调试）。确认无误后再部署到阿里云服务器。

---

## 流程概览（从零到可测）

1. 克隆仓库 → 创建并激活 Python venv → `pip install -r requirements.txt`
2. 复制 `.env`，执行 `docker compose up -d db`，等待 `db` 为 `healthy`
3.（按需）在 `.env` 填写 Apify、百炼等密钥
4. `pytest tests/` 跑通单元测试
5. 准备小样本 CSV，执行 `python -m pipeline.seed_import --csv ...`
6.（按需）插入 `tweets` → 跑特征与 SPS，让 Dashboard 的 Candidates 等有数据
7. 本机启动 `python -m server.app` 与 `streamlit run dashboard/app.py ...`，浏览器验证

**Compose 两种用法**：

| 方式 | 命令 | 适用场景 |
|------|------|----------|
| **仅数据库（推荐本地调试）** | `docker compose up -d db` | 本机 Python 跑 Flask / Streamlit，便于断点与改代码即生效 |
| **全栈容器** | `docker compose up -d` | 起 `db`、`server`、`dashboard`、`cron`；会占用 5000、8501 等端口，与「本机起 Flask/Streamlit」二选一 |

---

## 一、环境要求

| 项目 | 说明 |
|------|------|
| 操作系统 | macOS / Linux / Windows（WSL2 推荐） |
| Python | 3.11+ |
| Docker Desktop | 用于运行 PostgreSQL 容器 |
| Git | 克隆与管理代码 |
| 本机端口 | 默认映射 **5432**；若已被占用，见下文 **3.0 端口冲突** |

### 数据库命名约定

全项目（本地 Docker、本机 `psql`、阿里云 RDS 等）建议统一如下，**避免连接串与实例实际库名不一致**。

| 项 | 正式名称 | 说明 |
|----|----------|------|
| **PostgreSQL 逻辑库名** | `craftifyx_miner` | 小写 + 下划线；与仓库目录名 `craftifyxminer` 对应，便于识别 |
| **数据库用户（应用连接用户）** | `miner` | Docker 官方镜像初始化用户；云上可在 RDS 建同名用户或使用厂商提供的账号，但 **`DATABASE_URL` 中的用户名必须与实际可连库用户一致** |
| **单一配置源** | `.env` | `POSTGRES_DB`、`POSTGRES_USER` 供 [docker-compose.yml](../docker-compose.yml) 的 `db` 服务使用；`DATABASE_URL` 中的**库名段、用户段、密码**须与上述及 `DB_PASSWORD` 一致 |

**修改库名或用户时**：

1. 同步改 `.env` 里 `POSTGRES_DB`、`POSTGRES_USER`、`DATABASE_URL`（密码含特殊字符时按 URL 编码）。
2. 本地 Docker：若卷已初始化过，需 `docker compose down -v` 后重建，或在已有实例上 `CREATE DATABASE` / 建新用户并授权（勿只改 `.env` 不改库）。
3. 云上：在控制台创建同名库与用户，或只改 `DATABASE_URL` 指向厂商给定的库名与用户（团队内约定一种写法即可）。

---

## 二、获取代码与 Python 虚拟环境

```bash
cd /path/to/craftifyxminer   # 换成你本机克隆路径，例如 ~/Documents/GitHub/craftifyxminer

python3 -m venv venv
# macOS / Linux:
source venv/bin/activate
# Windows CMD:
# venv\Scripts\activate.bat
# Windows PowerShell:
# venv\Scripts\Activate.ps1

pip install -U pip
pip install -r requirements.txt
```

**说明**：后续所有命令均在**项目根目录**、且**已激活 venv** 的前提下执行。

---

## 三、仅用 Docker 启动 PostgreSQL（推荐）

项目自带 [docker-compose.yml](../docker-compose.yml)，其中 `db` 服务会：

- 使用镜像 `postgres:15-alpine`
- 将 [db/schema.sql](../db/schema.sql) 与 [db/indexes.sql](../db/indexes.sql) 挂载到 `docker-entrypoint-initdb.d`，**仅在数据卷首次初始化时**自动执行建表与索引
- 默认映射本机端口 `5432`

### 3.0 端口冲突（可选）

若本机 **5432** 已被占用，可改 [docker-compose.yml](../docker-compose.yml) 中 `db` 的 `ports`，例如改为宿主机 `5433`：

```yaml
ports:
  - "5433:5432"
```

同时把 `.env` 里的 `DATABASE_URL` 主机端口改为 `5433`（例：`postgresql://miner:密码@localhost:5433/craftifyx_miner`）。改完后如容器已在跑，需 `docker compose up -d db` 重新创建端口映射。

### 3.1 准备 `.env`

```bash
cp .env.example .env
```

编辑 `.env`，至少设置（示例密码请改成你自己的；`POSTGRES_*` 与 `DATABASE_URL` 须与 [数据库命名约定](#数据库命名约定) 一致）：

```env
POSTGRES_DB=craftifyx_miner
POSTGRES_USER=miner
DB_PASSWORD=your_local_strong_password

# 库名、用户名、密码须与上面一致
DATABASE_URL=postgresql://miner:your_local_strong_password@localhost:5432/craftifyx_miner
```

Docker Compose 会在**项目根目录**自动读取 `.env`，将 `POSTGRES_DB`、`POSTGRES_USER`、`DB_PASSWORD` 注入 `db` 容器（见 [docker-compose.yml](../docker-compose.yml)）。应用代码侧由 [config/settings.py](../config/settings.py) 的 `load_dotenv()` 加载同一 `.env` 中的 `DATABASE_URL`。

### 3.2 仅启动数据库容器

```bash
docker compose up -d db
```

等待健康检查通过（约 10–30 秒）：

```bash
docker compose ps
```

应看到 `db` 为 `healthy`。

### 3.3 验证数据库与表

若本机已安装 `psql`：

```bash
psql "postgresql://miner:your_local_strong_password@localhost:5432/craftifyx_miner" -c "\dt"
```

应能看到 `creators`、`tweets`、`creator_features` 等表。

**若 `\dt` 为空**：常见原因是**数据卷曾经初始化过**，但那时没有挂载 `schema.sql`。处理方式二选一：

1. **清空卷重建（会删本地 PG 数据）**：

   ```bash
   docker compose down -v
   docker compose up -d db
   ```

2. **手动执行 SQL**：

   ```bash
   psql "postgresql://miner:your_local_strong_password@localhost:5432/craftifyx_miner" -f db/schema.sql
   psql "postgresql://miner:your_local_strong_password@localhost:5432/craftifyx_miner" -f db/indexes.sql
   ```

---

## 四、配置其余 API（本地测试最小集）

完整模板见 [.env.example](../.env.example)。按你要测的功能填写即可：

| 场景 | 建议 |
|------|------|
| 仅 `pytest` + 规则/特征/SPS 单测 | 可不填真实 Apify、百炼；`tests/test_ai_filter.py` 使用 **unittest.mock**，一般**不需要**真实 LLM Key 即可通过 |
| 真实调用 **LLM Bio 过滤** | 配置 `DASHSCOPE_API_KEY`（或 `.env.example` 中其他 provider），并设置 `LLM_PROVIDER` / `LLM_MODEL` |
| 真实 **Apify 抓取** | 配置 `APIFY_API_TOKEN`、`APIFY_WEBHOOK_SECRET` |
| Flask / Streamlit | `FLASK_SECRET_KEY`、端口变量等 |

环境变量由 [config/settings.py](../config/settings.py) 的 `load_dotenv()` 从项目根 `.env` 加载；不要在代码里硬编码密钥。

在 `.env` 中继续填写示例（测试「导入 + Dashboard + 部分管道」时，**可先不填 Apify**；要测 **真实 LLM 过滤** 则必须配置百炼或其一）：

```env
# --- Apify（真实跑抓取时再填；仅 pytest/规则筛选用不到）---
APIFY_API_TOKEN=apify_api_你的token
APIFY_WEBHOOK_SECRET=本地随机字符串即可

# --- 阿里云百炼（测 AI 过滤时必填其一）---
DASHSCOPE_API_KEY=sk-你的Key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_PROVIDER=dashscope
LLM_MODEL=qwen3.5-plus
LLM_BATCH_SIZE=50

FLASK_SECRET_KEY=本地随机长字符串
FLASK_PORT=5000
STREAMLIT_PORT=8501

DAILY_APIFY_BUDGET_USD=20
MONTHLY_LLM_BUDGET_USD=10
```

**注意**：

- 不要把 `.env` 提交到 Git。
- `DATABASE_URL` 中的密码若含特殊字符，需按 URL 规则编码。

---

## 五、运行单元测试（pytest）

```bash
pytest tests/ -v
```

期望：全部通过。`tests/test_ai_filter.py` 对 LLM 调用做了 mock，**通常不依赖外网或真实 Key**。若个别用例失败，先确认已在仓库根目录执行、venv 已安装 [requirements.txt](../requirements.txt)，且未误删测试依赖。

仅跑快速子集：

```bash
pytest tests/test_bio_rule_filter.py tests/test_feature_engine.py tests/test_sps_scorer.py -q
```

---

## 六、小样本 CSV 与种子导入

### 6.1 新建文件 `data/sample_seeds.csv`（可放在任意路径，下面用相对路径示例）

CSV **至少包含列** `username`。可选列与 [pipeline/seed_import.py](../pipeline/seed_import.py) 一致：`total_sales`、`bio`、`website`、`followers`、`following`、`tweets_count`、`has_merch_experience`（缺省 `total_sales` 时按 0 处理）。建议带 `total_sales` 以便验证 Tier 展示。

示例内容：

```csv
username,total_sales,bio,website,followers,following,tweets_count,has_merch_experience
demo_creator_s,3200,"illustrator | commissions open",https://linktr.ee/demo,12000,500,800,true
demo_creator_a,900,"fan artist booth",https://booth.pm/demo,8000,600,600,true
demo_creator_b,200,"indie dev",https://carrd.co/demo,5000,700,400,false
demo_fan,50,"fan account for someone",,1500,1200,200,false
demo_grey,0,"just creating things",,300,400,50,false
```

Tier 规则（与代码一致）：`S` > 2000，`A` > 500，`B` > 100，其余为 `C`。

### 6.2 执行导入

```bash
python -m pipeline.seed_import --csv data/sample_seeds.csv
```

### 6.3 SQL 抽查

```bash
psql "$DATABASE_URL" -c "SELECT username, is_seed, seed_tier, total_sales FROM creators ORDER BY total_sales DESC;"
```

（若未设置环境变量 `DATABASE_URL`，可在 shell 里 `export DATABASE_URL=...` 或把连接串写在命令里。）

---

## 七、为 Dashboard 准备「有特征与 SPS」的数据（可选）

Candidates 等页面会读 `creator_features`、`creator_scores`。流程是：**先有推文** → **算特征** → **算 SPS**。未跑 Apify 时，可在导入种子后**手工插入几条 `tweets`**。

### 7.1 插入示例推文（将 `1` 换成实际 `creator_id`）

先查 id：

```bash
psql "$DATABASE_URL" -c "SELECT id, username FROM creators;"
```

```sql
INSERT INTO tweets (tweet_id, creator_id, likes, retweets, replies, views, created_at, text, media_urls)
VALUES
  ('t_demo_1', 1, 100, 20, 5, 1000, NOW(), 'fanart showcase @friend', ARRAY['https://pbs.twimg.com/media/x.jpg'])
ON CONFLICT (tweet_id) DO NOTHING;
```

可在 `psql` 里粘贴执行，或保存为 `tmp_seed_tweets.sql` 后 `psql "$DATABASE_URL" -f tmp_seed_tweets.sql`。

### 7.2 计算特征与 SPS

顺序：**必须先写入 `creator_features`，再调用 `score_creator`**（内部会读特征行；若 `creator_scores` 尚无记录，`creator_type` 默认为 `content_creator`）。

单用户示例（将 `1` 换成你的 `creator_id`）：

```bash
python - <<'PY'
from pipeline.feature_engine import compute_features_for_creator
from pipeline.sps_scorer import score_creator

cid = 1
compute_features_for_creator(cid)
print(score_creator(cid))
PY
```

批量（对所有「有推文、尚无特征行」的用户算特征，再对所有「有特征、尚无评分行」的用户算 SPS）：

```bash
python - <<'PY'
from pipeline.feature_engine import compute_all_pending
from pipeline.sps_scorer import score_all_pending

print("computed features rows:", compute_all_pending())
print("scored rows:", score_all_pending())
PY
```

说明：`compute_all_pending()` 只处理**至少有一条 tweet 且尚无 `creator_features` 行**的创作者；若你刚插入 tweet，跑一遍即可。

---

## 八、启动 Flask 与 Streamlit（本机进程）

**终端 1 — Flask：**

```bash
python -m server.app
```

或使用 gunicorn（与生产接近）：

```bash
gunicorn -w 1 -b 127.0.0.1:5000 server.app:app
```

**终端 2 — Dashboard：**

```bash
streamlit run dashboard/app.py --server.port 8501 --server.address 127.0.0.1
```

### 8.1 验证 URL

| 用途 | 地址 |
|------|------|
| 健康检查 | http://127.0.0.1:5000/health |
| 内部 API 示例 | http://127.0.0.1:5000/api/daily-stats |
| Streamlit 首页 | http://127.0.0.1:8501 |

侧边栏可进入多页面：`Daily Report`、`Candidates`、`Outreach`、`Cost Monitor`。

---

## 九、停止与清理

- 停止 Flask / Streamlit：`Ctrl+C`。
- 停止仅 PG 容器、保留数据：

  ```bash
  docker compose stop db
  ```

- 停止并删除卷（**清空本地数据库**）：

  ```bash
  docker compose down -v
  ```

---

## 十、常见问题

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `connection refused` 连不上 5432 | Docker 未启动或端口占用 | `docker compose ps`；本机是否已有其他 PG 占 5432 |
| 表不存在 | 卷已初始化过但未执行 schema | 见上文「手动执行 SQL」或 `down -v` 重建 |
| `ModuleNotFoundError` | 未在根目录执行或未激活 venv | `cd` 到仓库根，`source venv/bin/activate` |
| pytest 部分失败 | 缺依赖或 mock 问题 | `pip install -r requirements.txt` 后重跑 |
| Dashboard 无候选人 | 无 `creator_scores` / 无特征数据 | 先导入种子、插入 tweets、跑 feature/sps |
| LLM 调用失败 | 未配置 `DASHSCOPE_API_KEY` 或欠费 | 检查百炼控制台与 `.env` |

---

## 十一、上服务器前自检清单

- [ ] `pytest tests/ -q` 通过  
- [ ] `docker compose up -d db` 健康，`psql` 能连上  
- [ ] `seed_import` 成功，`creators` 有数据  
- [ ] （可选）特征与 SPS 脚本跑通，`creator_features` / `creator_scores` 有行  
- [ ] `http://127.0.0.1:5000/health` 返回正常  
- [ ] `http://127.0.0.1:8501` 能打开 Dashboard  
- [ ] `.env` 未提交到 Git  

完成以上后，再将**同一套环境变量**改为阿里云 RDS 连接串，在服务器上部署应用即可（数据库可不再用本地 Docker）。

---

## 十二、参考文件路径

| 文件 | 说明 |
|------|------|
| [.env.example](../.env.example) | 环境变量模板（含 `POSTGRES_DB` / `POSTGRES_USER`） |
| [config/settings.py](../config/settings.py) | 从 `.env` 加载配置（`load_dotenv`） |
| [docker-compose.yml](../docker-compose.yml) | 含 `db`、`server`、`dashboard`、`cron` 定义 |
| [db/schema.sql](../db/schema.sql) | 表结构 |
| [db/indexes.sql](../db/indexes.sql) | 索引 |
| [pipeline/seed_import.py](../pipeline/seed_import.py) | 种子 CSV 导入 |
| [tests/](../tests/) | pytest 用例（含 `test_ai_filter` 等） |
