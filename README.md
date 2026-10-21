# DevPipeline

AI 辅助软件开发平台：需求录入 → 需求分析 → 系统设计 → 编码 → PR 评审，每个阶段结束停人工审批（Human-in-the-Loop）。

当前进度：**M1 / M2 完成**（需求管理 + LangGraph 4 阶段流水线 + 4 个人工审批门 + 运行详情审批界面）。M3（实时可观测性）、M4、M5 待做。

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

数据隔离说明：M1 的集成测试用「外层事务 + savepoint」，测试里的 `commit()` 只释放 savepoint，用例结束整体回滚；
**流水线（M2）测试不能这么做** —— 执行器用独立连接读写，看不到未提交事务，所以那批用例真实提交，跑完在 fixture 里按顺序删行并清掉 PG 的 checkpoint 线程。

## M1 已实现

- 后端分层：`api / services / models / schemas / core / db`，统一错误体 `{code, message, details, trace_id}`、`X-Trace-Id` 响应头。
- 数据：`projects` / `requirements` / `requirement_versions` 三张表，Alembic 迁移 `e0409de16feb`，
  `utf8mb4_unicode_ci` + `LONGTEXT` + `DATETIME(3)`。
- 接口：项目 CRUD、需求 CRUD、需求版本（列表 / 新增 / `.md` 上传 / 按版本取正文）、`/healthz`、`/readyz`。
- 版本语义：每次保存或上传都追加一行版本并推进 `current_version_no`，追加时对需求行加 `FOR UPDATE`，并发不撞唯一键。
- 前端：项目列表、需求列表（搜索/分页）、需求详情（Markdown 编辑 + 预览、保存新版本、上传 `.md`、版本历史抽屉）。

## M2 已实现

- 图：`analyze_requirement → gate_analysis → design_system → gate_design → coding → gate_coding → pr_review → gate_review`，
  gate 内 `interrupt()`，恢复用 `Command(resume={decision, feedback?, edited_content?})`，同一 `thread_id`。
- 决策语义：通过 / 改后通过（覆盖正文并生成新产物版本）/ 驳回（同阶段 `revision+1` 重跑，意见注入 prompt）/ 中止。
- 评审回退：`review` 驳回 → 回到 `coding`，`review_round` 每轮 +1，超过 `max_review_rounds` 置 `failed` + `review_round_exceeded`。
- checkpointer：PostgreSQL 17 + psycopg 连接池，启动 `setup()` 建表；**连接池与 pipeline 模式互斥**（源码强制）。
- 数据：`pipeline_runs` / `stage_runs` / `artifacts` / `stage_approvals`（迁移 `a283b6a9eefc`），执行器按图状态幂等落库。
- 接口：启动运行、运行列表/详情、`pending-approval`、`approval`、`states`（`aget_state_history`）、产物列表/正文/人工编辑、`retry`、`cancel`。
- 一致性：读路径以 `aget_state` 为准校正 MariaDB；「审批已落库、resume 还没消费」的窗口里状态保持 `running` 且不再暴露待审批（防重复提交）；
  进程重启时按 checkpoint 把未完成的 run 重新挂上。
- 队列：M2 用进程内 `asyncio` 队列（`app/queue/inline.py`），M3 换 arq + Redis，调用点只依赖 `submit()`。
- 前端：`/runs` 列表（状态筛选/分页）、`/runs/:id`（4 阶段进度、待审批面板：通过/改后通过/驳回必填意见/中止、
  产物预览与人工编辑、checkpoint 状态历史、失败信息、3s 轮询）；需求详情的「启动流水线」已接通并按 `version_no` 起跑。
- 需求状态跟随最新一次运行（`queued/running/waiting_approval/done/failed/cancelled`）：执行器在每次状态切换时同步，
  读接口 reconcile 也会自愈历史数据（只改 `latest_run_id` 指向当前 run 的那条需求）。

## 未实现（后续里程碑）

- M3：arq worker、`astream_events` → Redis → SSE、Vue Flow 实时图、token/工具调用流式面板、暂停与回溯（`fork`）。
- M4：AGENTS.md / Skills / MCP 配置与注入。
- M5：编码沙箱（git worktree / Docker）+ 白名单命令 + GitHub PR + 评审回退落代码。

## 已知约束（踩过的坑，别再踩）

| 约束 | 原因 |
|---|---|
| `uvicorn` 必须 `0.31.x` | 0.36+ 在 Windows 用 `asyncio.Runner(loop_factory=…)` 强制 ProactorEventLoop，psycopg 直接报 "cannot use the ProactorEventLoop" |
| `redis` 必须 `<6` | arq 0.28 仍锁 `redis[hiredis]>=4.2,<6`，uv 解析 6.x 无解 |
| `alembic.ini` 只能写 ASCII | configparser 用系统 locale（中文 Windows 是 GBK）读它，中文注释会 `UnicodeDecodeError` |
| 不建外键、不声明 ORM relationship | 关系用显式查询表达；无外键时 ORM 猜不出 join 条件，且异步 lazy load 会炸 |
| 集成测试用 savepoint 回滚 | 远程库没有独立测试库权限，直接清表会伤数据；但流水线用例必须真实提交（执行器用独立连接） |
| checkpointer 用连接池，不开 pipeline | `AsyncPostgresSaver` 对 `AsyncConnectionPool + pipe` 直接 raise，二者互斥 |
| `get_checkpointer()` 必须加锁 | 启动兜底与执行器会并发初始化，实测会建出两个池并泄漏 psycopg worker 任务 |
| Windows 事件循环统一 selector | M2 的 psycopg 不支持 Proactor；`backend/main.py` 入口在 uvicorn 建 loop 前设置（`app/core/server.py`） |
