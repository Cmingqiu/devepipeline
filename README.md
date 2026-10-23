# DevPipeline

AI 辅助软件开发平台：需求录入 → 需求分析 → 系统设计 → 编码 → PR 评审，每个阶段结束停人工审批（Human-in-the-Loop）。

当前进度：**M1 / M2 / M3 / M4 完成；M5 沙箱 + PR + 工作区清理完成**。剩余：Docker 沙箱模式、多 provider / 每阶段模型、GitLab PR。

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

# 3) arq worker（M3 起流水线在 worker 里跑；QUEUE_BACKEND=arq 时必须起）
conda run -n devpipeline python worker.py
#   为什么不用 `arq app.worker.main.WorkerSettings`：`python -m arq` 自建事件循环，
#   Windows 上是 Proactor，psycopg 会直接报错；worker.py 先在建 loop 前钉死 selector。
#   worker 不在时后端会检测心跳缺失并回退进程内执行（run 不会卡在「排队中」），
#   但日志会打 worker_absent_fallback_inline；长期使用请把 worker 起上。

# 4) 前端（另一个终端，127.0.0.1:5173，/api 已代理到 8000）
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
- 队列：`QUEUE_BACKEND=arq`（Redis + worker 进程）或 `inline`（进程内，零依赖）；调用方只依赖 `app/queue/dispatcher.py`。
- 前端：`/runs` 列表（状态筛选/分页）、`/runs/:id`（4 阶段进度、待审批面板：通过/改后通过/驳回必填意见/中止、
  产物预览与人工编辑、checkpoint 状态历史、失败信息、3s 轮询）；需求详情的「启动流水线」已接通并按 `version_no` 起跑。
- 需求状态跟随最新一次运行（`queued/running/waiting_approval/done/failed/cancelled`）：执行器在每次状态切换时同步，
  读接口 reconcile 也会自愈历史数据（只改 `latest_run_id` 指向当前 run 的那条需求）。

## M3 已实现（后端）

- 事件：`run_events`（迁移 `caaa494def20`）存 `{seq, ts, run_id, stage, type, payload}`；`seq` 用 Redis `INCR` 全局单调，
  Redis 不可用时退化为「库里最大值 +1」并告警。
- 实时：每次 emit 同时 `PUBLISH run:{id}:events`（实时）与批量落库（回放）；token 合并窗口 100 ms / 200 字符，
  一次 LLM 调用产生几十条 `llm_token` 而不是几万条。
- 流式前提：节点用 `model.astream()` 聚合，模型侧必须 `streaming=True`；非流式时 LangGraph 的 messages 模式只会吐一个整块。
- SSE：`GET /api/v1/runs/{id}/stream`，支持 `Last-Event-ID` 回放 + Redis 实时订阅 + 15 s 心跳；
  收到 `run_finished` 主动关闭；终态但缺终止事件时补一条再关。
- 历史：`GET /api/v1/runs/{id}/events?after_seq=&page_size=&types=`。
- 队列：`QUEUE_BACKEND=arq` 走 Redis 队列（worker 进程执行），Redis 不可用时自动回退进程内队列；
  取消检查节流到 1 s/次（每 token 查一次远程 MariaDB 会把流式拖到 4 token/s）。
- 踩坑修复：等审批时**不能**发 `run_finished`（否则前端会关掉流）；`interrupt` 才是暂停信号；
  SSE 的 `stage` 必须是阶段枚举，不能透出 langgraph 节点名（否则前端 token 缓冲对不上，面板全空）。
- 前端：`useRunStream` 订阅 10 种事件（token 按阶段拼接、时间线 2000 条上限、断线由浏览器重连带 `Last-Event-ID`）；
  `PipelineGraph` 用 Vue Flow 画 8 个节点（4 阶段 + 4 审批门，五态配色）；运行详情用 SSE 替代轮询，
  连接失败回退 5 s 轮询；实时流面板自动跟随、时间线着色。
- 暂停/继续：`POST /runs/{id}/pause` 置 `status=paused`，执行器在下一个节点边界停下并落 checkpoint、发 `run_paused`；
  `resume` 置回 `running` 并用 `continue_run` 入队，从断点继续。等待审批时拒绝暂停（409）。
- checkpoint fork：`POST /runs/{id}/fork`（`{checkpoint_id, from_stage?}`）新建 run + 新 thread，
  从目标 checkpoint 取初值、清空 `from_stage` 及之后产物、复制之前的 artifacts，再从该阶段节点重跑；
  事件 `forked` 记录来源。前端在状态历史每条 checkpoint 上提供「从此处 fork」。

## M4 已实现

- 数据：`agent_docs`（版本 + active）、`skills` / `skill_files`、`mcp_configs`、`credentials`；`projects` 增加 `repo_url / repo_provider / default_branch / credential_id`（迁移 `acf41347204f`）。
- AGENTS.md：PUT 产生新版本并置为生效（相同内容不产生新版本），版本列表只回元信息；204 = 未配置。
- Skills：上传 zip（≤20 MB、解压 ≤50 MB、≤200 文件），拒绝 `..` / 绝对路径 / 符号链接，必须含 `SKILL.md`；
  文本入库供在线预览、二进制只落磁盘；同名技能覆盖。
- MCP：按 name 整体覆盖保存；输出时把 token/secret/key/password 掩码成 `****1234`；连通性测试走
  `langchain-mcp-adapters`（单 server 15 s 超时，失败不拖垮其它 server）。
- 仓库与凭证：Fernet 加密（SHA-256 派生 `APP_SECRET_KEY`，带 `key_version`），接口只回末 4 位；`git ls-remote` 测试连接，回显时替换掉带 token 的 URL。
- 注入：run 初始化时冻结 AGENTS.md 全文 + 每个技能 `SKILL.md`（≤4k/个、≤12k 总），作为 `agents_md` / `skill_index` 进入 prompt 上下文。
- 编码 agent 工具：执行器按项目加载 MCP 工具（stdio / streamable_http，配置里 `$CRED:<id>` 加载时解密）+
  `read_skill_file`（按需读技能包脚本），工具名加 server 前缀；编码节点最多 6 轮工具循环，
  工具事件经 `get_stream_writer()` → custom 流 → SSE 实时推送；加载失败/超时降级为无工具并把原因写进时间线。
- 前端：`/projects/:id/settings` 四个 Tab（AGENTS.md 编辑与版本、Skills 上传/文件树预览、MCP JSON 编辑与测试、仓库与凭证），凭证只显示 hint；运行时间线展示工具调用与结果。
- 事件落库修复：`close()` 取消在途 flush 会整批丢事件（实测丢 `interrupt`），改为取消时把批次放回缓冲并等任务退出。

## M5 已实现（编码沙箱 + GitHub PR）

- `code_workspaces`（迁移 `503586198009`）：每个 run 一个 clone 目录 `workspaces/run-{id}` + `devpipeline/run-{id}` 分支，记录 base/head sha。
- 命令执行：按 argv 拆分、**不经 shell**；白名单（git / pytest / pnpm / npm / node / ruff / tsc / dotnet / go…）+ 危险模式拒绝 + 120s 默认超时 + 8KB 输出截断。
- 沙箱工具：`sandbox_list_files` / `read_file` / `write_file` / `run_command` / `git_diff`；coding 产物 = 模型说明 + `git diff` + 命令与测试记录。
- 隔离与恢复：路径越界拒绝；审批后继续执行复用同一目录（先校验 HEAD，坏目录自动重建）。
- 失败降级：沙箱起不来时 coding 退回纯文本 diff 草案，原因写进时间线（`sandbox_unavailable`）。
- `pull_requests`（迁移 `7b1f3c9d24ae`）：评审阶段先提交沙箱改动、推送分支、再创建/复用 GitHub PR；
  一个 run 每个 provider 一条，评审驳回重跑时更新同一条（`head_sha` 跟随最新提交）。
- PR 客户端：`app/vcs/`（`RepoRef` / `PullRequestInfo` / `VcsClient` Protocol + httpx 实现的 `GitHubClient`）；
  支持 `https://…`、`git@…`、`ssh://…` 地址解析，`repo_provider` 可覆盖企业域名推断；GitLab 只抛「暂未实现」。
- 幂等与降级：同分支 PR 已存在时（GitHub 422）回查复用；推送/API 失败只发 `error(pr_unavailable)` 事件，
  评审继续用本地 diff；`pull_request_created` 事件实时进时间线；`GET /api/v1/runs/{id}/pull-requests` 暴露结果。
- 前端：运行详情页 Pull Request 面板（provider/状态/分支/链接），时间线支持 PR 创建事件。

## M5 已实现（工作区清理）

- 成功即清：run 到 `succeeded` 时执行器自动删除 `workspaces/run-{id}` 并写 `code_workspaces.cleaned_at`，
  时间线补一条 `progress`（`cleaned_workspaces`）。开关：`WORKSPACE_CLEANUP_ON_SUCCESS`（默认 true）。
- 失败/取消保留：便于排查，不自动删；由保留期兜底（`WORKSPACE_RETENTION_DAYS`，默认 7 天），
  worker 每日 03:30 跑 `purge_workspaces`，同时清理库里已无对应行的孤儿目录。
- 手动清理：`DELETE /api/v1/runs/{id}/workspaces`，只允许终态 run（进行中/等审批返回 409，避免抽走正在用的沙箱）。
- 安全边界：只删 `workspaces` 根目录内的路径（DB 被改坏也不会变成任意文件删除）；单目录删除失败只告警不中断。

## 未实现（后续里程碑）

- M5 剩余：Docker 沙箱模式；PR 状态（merged/closed）只在建 PR 时写入，没有轮询刷新。
- M4 剩余：多 provider / 每阶段模型选择（`llm_providers` / `model_bindings` 表尚未建，当前走环境变量单一 provider）；
  技能仍以 SKILL.md 全量注入为主，`read_skill_file` 只覆盖额外脚本/资料。
- GitLab：`VcsClient` 已抽象，`build_vcs_client` 对 gitlab 直接抛错，实现待补。

## 已知约束（踩过的坑，别再踩）

| 约束 | 原因 |
|---|---|
| `uvicorn` 必须 `0.31.x` | 0.36+ 在 Windows 用 `asyncio.Runner(loop_factory=…)` 强制 ProactorEventLoop，psycopg 直接报 "cannot use the ProactorEventLoop" |
| `redis` 必须 `<6` | arq 0.28 仍锁 `redis[hiredis]>=4.2,<6`，uv 解析 6.x 无解 |
| worker 用 `python worker.py` 启动，不用 `-m arq` | `python -m arq` 自建事件循环（Windows=Proactor），psycopg 直接报 "cannot use the ProactorEventLoop" |
| 节点调模型必须 `astream()` + `streaming=True` | 非流式时 LangGraph 的 messages 模式只吐一个整块，SSE 面板就没有增量 |
| 取消检查必须节流 | 每 token 查一次远程 MariaDB 会把流式拖到 4 token/s（实测）；改为 1 s/次，节点边界必查 |
| 等审批不发 `run_finished` | 该事件会让前端关掉 SSE；暂停语义用 `interrupt` |
| `alembic.ini` 只能写 ASCII | configparser 用系统 locale（中文 Windows 是 GBK）读它，中文注释会 `UnicodeDecodeError` |
| 不建外键、不声明 ORM relationship | 关系用显式查询表达；无外键时 ORM 猜不出 join 条件，且异步 lazy load 会炸 |
| 集成测试用 savepoint 回滚 | 远程库没有独立测试库权限，直接清表会伤数据；但流水线用例必须真实提交（执行器用独立连接） |
| checkpointer 用连接池，不开 pipeline | `AsyncPostgresSaver` 对 `AsyncConnectionPool + pipe` 直接 raise，二者互斥 |
| `get_checkpointer()` 必须加锁 | 启动兜底与执行器会并发初始化，实测会建出两个池并泄漏 psycopg worker 任务 |
| Windows 事件循环统一 selector | M2 的 psycopg 不支持 Proactor；`backend/main.py` 入口在 uvicorn 建 loop 前设置（`app/core/server.py`） |
| worker 心跳 `devpipeline:health` | 每 30 s 刷新；api 入队前检查心跳，没有就回退进程内执行，否则 run 会永远停在「排队中」（2026-10-23 实测） |
| arq job id 必须确定性 | `run:{id}:start` / `run:{id}:continue` / `run:{id}:resume:{payload hash}`；否则双击启动或 api 重启 requeue 会让**两个 worker 同时跑同一个 run**（实测产生两个 analysis artifact、事件翻倍） |
| 事件 flush 取消要把批次放回 | `close()` 取消在途 flush 时若直接丢弃批次，会丢尾部事件（实测丢 `interrupt`）；取消时 `batch + buffer` 回填再等任务退出 |
| 技能包 zip 必须做路径校验 | 拒绝 `..`/绝对路径/符号链接，限制 zip ≤20 MB、解压 ≤50 MB、≤200 文件；否则上传即任意写文件 |
| `APP_SECRET_KEY` 不能随意更换 | 凭证密文由它派生；换了之后旧凭证解不开（`credential_decrypt_failed`），需要重新填 token |
| 工具对象不能进 state | MCP 客户端/句柄不可序列化，进 checkpoint 会炸；执行器按 run 注册进程内 registry，节点按 run_id 取 |
| MCP 工具输出要归一化 | adapters 返回 content blocks（[{"type":"text","text":"5"}]），直接 str 回灌模型会很脏；先拆成纯文本 |
| Windows selector loop 不支持子进程 | psycopg 要求 selector，但 selector 没有 `create_subprocess_exec`（实测 NotImplementedError）；沙箱命令统一 `asyncio.to_thread(subprocess.run)` |
| 沙箱命令必须走白名单 | 不经 shell 只解决注入，不解决 `rm -rf`；白名单 + 危险模式双重拦截，默认 120s 超时 |
| workspace 复用前要校验 HEAD | 中断留下的半个目录直接复用会让 clone 状态错乱；`git rev-parse --verify HEAD` 失败就重建 |
| 沙箱 git commit 的 message 必须 argv 直传 | `run_command` 走 shlex 拆分，未加引号的 message（含空格/中文）会被拆成多条 pathspec，git 报 `pathspec did not match`；`Workspace.commit` 改用 `_run_git` |
| push 带 token 的命令必须脱敏 | `git push https://x-access-token:<token>@…` 会进命令记录，git 报错还会回显完整 URL；`display_command` + 输出替换成 `***` |
| PR 失败不能阻断评审 | 推送/API 失败只发 `error(pr_unavailable)` 并继续本地 diff 评审；PR 是交付物不是前置条件 |
| 暂停/取消只能在节点边界生效 | 进程内队列无法强杀正在跑的协程；DB `status` 是唯一控制通道，每个 `updates` 边界必查 |
| fork 入口用 `aupdate_state(as_node=前一个 gate)` | `Command(goto=...)` 作为图输入在 LangGraph 1.1.6 实测被忽略（从 START 重跑并覆盖 seed）；只有 `as_node` 能让新 thread 的 next 指向 `from_stage` 节点 |
| workspace 清理只允许终态 | 等审批/运行中的目录还要被 resume 复用，删了等于抽走正在用的沙箱；自动路径只在 `succeeded` 执行 |
| 保留期清理要扫孤儿目录 | run 行被删后目录没人认领，只按 DB 行清会永久残留；按目录 mtime 扫并顺手清 |
