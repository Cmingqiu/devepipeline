# DevPipeline

AI 辅助软件开发平台：需求录入 → 需求分析 → 系统设计 → 编码 → PR 评审，每个阶段结束停人工审批（Human-in-the-Loop）。

当前进度：**M1（项目脚手架 + 需求管理）已完成**，流水线编排在 M2。

- 整体架构、双库边界、LangGraph 状态机、ER、API、页面清单：[docs/architecture.md](docs/architecture.md)
- VPS 基础设施（MariaDB / PostgreSQL / Redis）启动与验收：[deploy/README.md](deploy/README.md)

## 目录

```
backend/    FastAPI + SQLAlchemy 2.0 async + Alembic（api / services / models / schemas 分层）
frontend/   Vue3 + Vite + TS + Pinia + Element Plus
deploy/     docker-compose（MariaDB 11.4 / PostgreSQL 17 / Redis 7 / Redis Commander）
docs/       架构设计
```

## 环境要求

| 项 | 值 | 说明 |
|---|---|---|
| Python | **3.11**（conda env `devpipeline`） | 系统默认 3.14 不可用；依赖已装在 `D:\miniconda\envs\devpipeline` |
| Node / pnpm | 24.x / 12.x | 仅前端需要 |
| 数据库 | 远程 MariaDB 11.4 + PostgreSQL 17 + Redis 7 | 本机无 Docker，走 VPS，见 `deploy/README.md` |

## 配置

后端配置在 `backend/.env`（**已 gitignore，内含真实密码**），关键项：

```dotenv
MARIADB_HOST=…            MARIADB_PORT=13306
MARIADB_USER=…            MARIADB_PASSWORD=…
MARIADB_DATABASE=devpipeline
POSTGRES_*                # M2 用（checkpointer）
REDIS_*                   # M3 用（arq + 事件广播）
LLM_KEY_DEEPSEEK=         # M2 起真实调用模型时需要
```

模板见 `deploy/README.md` §5。`APP_SECRET_KEY` 用于凭证加密（M4），已自动生成。

## 启动

```powershell
# 1) 迁移（首次/每次拉代码后）
cd backend
conda run -n devpipeline python -m alembic upgrade head

# 2) 后端 API（127.0.0.1:8000）
conda run -n devpipeline python main.py
#   换端口/开热重载：python main.py --port 8010 / python main.py --reload
#   也支持环境变量：API_HOST / API_PORT / API_RELOAD / API_LOG_LEVEL
#   等价入口：python -m app（两者共用 app/core/server.py，Windows selector 已在建 loop 前设置）

# 3) 前端（另一个终端，127.0.0.1:5173，/api 已代理到 8000）
cd frontend
pnpm install
pnpm dev
```

API 文档：<http://127.0.0.1:8000/docs>（OpenAPI JSON 在 `/api/v1/openapi.json`）。

## 验证

```powershell
cd backend
conda run -n devpipeline python -m pytest tests/unit -q            # 纯单元，不连库
conda run -n devpipeline python -m pytest tests/integration/maria -q  # 连远程 MariaDB
conda run -n devpipeline python -m ruff check app tests

cd ..\frontend
pnpm build && pnpm test
```

服务起来后的冒烟（期望输出已写明）：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
# {"status":"ok"}

Invoke-RestMethod http://127.0.0.1:8000/readyz
# {"status":"ok","checks":{"mariadb":"ok","postgres":"skipped","redis":"skipped"}}

$p = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/projects `
  -ContentType 'application/json; charset=utf-8' -Body '{"name":"示例项目"}'
# slug 自动生成；中文标题会兜底成 p-xxxxxxxx
```

数据隔离说明：集成测试用「外层事务 + savepoint」模式，测试里的 `commit()` 只释放 savepoint，用例结束整体回滚，
**不会污染真实数据，也不需要清表**。

## M1 已实现

- 后端分层：`api / services / models / schemas / core / db`，统一错误体 `{code, message, details, trace_id}`、`X-Trace-Id` 响应头。
- 数据：`projects` / `requirements` / `requirement_versions` 三张表，Alembic 迁移 `e0409de16feb`，
  `utf8mb4_unicode_ci` + `LONGTEXT` + `DATETIME(3)`。
- 接口：项目 CRUD、需求 CRUD、需求版本（列表 / 新增 / `.md` 上传 / 按版本取正文）、`/healthz`、`/readyz`。
- 版本语义：每次保存或上传都追加一行版本并推进 `current_version_no`，追加时对需求行加 `FOR UPDATE`，并发不撞唯一键。
- 前端：项目列表、需求列表（搜索/分页）、需求详情（Markdown 编辑 + 预览、保存新版本、上传 `.md`、版本历史抽屉）。

## 未实现（后续里程碑）

- M2：LangGraph 流水线 + 4 个审批门 + PostgreSQL checkpointer + `Command(resume)` 恢复。
- M3：arq worker、`astream_events` → Redis → SSE、Vue Flow 实时图、取消/暂停/重试/回溯。
- M4：AGENTS.md / Skills / MCP 配置与注入。
- M5：编码沙箱（git worktree / Docker）+ 白名单命令 + GitHub PR + 评审回退。

前端「启动流水线」按钮在 M1 处于禁用状态，M2 接通后开放。

## 已知约束（踩过的坑，别再踩）

| 约束 | 原因 |
|---|---|
| `uvicorn` 必须 `0.31.x` | 0.36+ 在 Windows 用 `asyncio.Runner(loop_factory=…)` 强制 ProactorEventLoop，psycopg 直接报 "cannot use the ProactorEventLoop" |
| `redis` 必须 `<6` | arq 0.28 仍锁 `redis[hiredis]>=4.2,<6`，uv 解析 6.x 无解 |
| `alembic.ini` 只能写 ASCII | configparser 用系统 locale（中文 Windows 是 GBK）读它，中文注释会 `UnicodeDecodeError` |
| 不建外键、不声明 ORM relationship | 关系用显式查询表达；无外键时 ORM 猜不出 join 条件，且异步 lazy load 会炸 |
| 集成测试用 savepoint 回滚 | 远程库没有独立测试库权限，直接清表会伤数据 |
| Windows 事件循环统一 selector | M2 的 psycopg 不支持 Proactor；`backend/main.py` 入口在 uvicorn 建 loop 前设置（`app/core/server.py`） |
