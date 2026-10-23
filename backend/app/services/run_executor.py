"""执行器：把图跑起来，并把 `last_stage` / interrupt 落成 MariaDB 记录。

输入/恢复三种形态：
- `start`     首次执行，传初始 state；
- `continue_run`  进程重启后从最后一个 checkpoint 续跑（input=None）；
- `resume_payload`  人工审批后 `Command(resume=...)`。
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.graph import NODE_TO_STAGE, build_graph
from app.agents.llm import ProviderNotConfigured, assert_provider_ready
from app.agents.tool_registry import clear_run_sandbox, clear_run_tools, set_run_tools
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.graph_db import get_checkpointer
from app.db.session import get_session_factory
from app.models import Artifact, CodeWorkspace, PipelineRun, Requirement, RequirementVersion, StageRun
from app.services.events import EventLogger
from app.services.prompt_context import load_prompt_context

logger = get_logger(__name__)

_compiled_graph = None

TOKEN_FLUSH_INTERVAL = 0.1  # 秒：token 合并窗口，避免每个字符一条事件
TOKEN_FLUSH_CHARS = 200

ERROR_MESSAGES: dict[str, str] = {
    "review_round_exceeded": "评审回退轮次超过上限，流水线终止，交人工处理",
    "aborted_by_human": "人工中止了本次运行",
}

# run.status -> requirement.status（前端需求列表/详情读的是 requirement.status）
REQUIREMENT_STATUS_MAP: dict[str, str] = {
    "queued": "queued",
    "running": "running",
    "waiting_approval": "waiting_approval",
    "succeeded": "done",
    "failed": "failed",
    "cancelled": "cancelled",
}


class RunCancelled(Exception):
    """协作式取消：执行器在每个 chunk 边界检查 DB 状态。"""


class _TokenBatcher:
    """把 LLM token 合并成 `llm_token` 事件；某节点第一次出 token 时补一条 `stage_started`。"""

    def __init__(self, events: EventLogger) -> None:
        self._events = events
        self._buffers: dict[str, list[str]] = {}
        self._last_flush: dict[str, float] = {}
        self._started: set[str] = set()

    async def add(self, stage: str | None, text: str) -> None:
        if not stage or not text:
            return
        if stage not in self._started:
            self._started.add(stage)
            self._last_flush[stage] = time.monotonic()
            await self._events.emit("stage_started", {"stage": stage}, stage=stage)
        buffer = self._buffers.setdefault(stage, [])
        buffer.append(text)
        now = time.monotonic()
        last = self._last_flush.get(stage, 0.0)
        pending_chars = sum(len(part) for part in buffer)
        if pending_chars >= TOKEN_FLUSH_CHARS or (now - last) >= TOKEN_FLUSH_INTERVAL:
            await self.flush(stage)

    async def flush(self, stage: str | None = None) -> None:
        for key in [stage] if stage else list(self._buffers):
            parts = self._buffers.pop(key, None)
            if not parts:
                continue
            self._last_flush[key] = time.monotonic()
            await self._events.emit("llm_token", {"text": "".join(parts)}, stage=key)

    async def flush_all(self) -> None:
        await self.flush()


async def get_graph():
    """编译后的图（进程内单例，绑定 PG checkpointer）。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph(checkpointer=await get_checkpointer())
    return _compiled_graph


def reset_graph() -> None:
    """checkpointer 关闭后必须一起丢弃（测试与热重载用）。"""
    global _compiled_graph
    _compiled_graph = None


def graph_config(run: PipelineRun) -> dict[str, Any]:
    return {"configurable": {"thread_id": run.thread_id}}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)  # 3.11+ 原生支持末尾的 Z
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


async def _initial_state(session, run: PipelineRun) -> dict[str, Any]:
    version = await session.get(RequirementVersion, run.requirement_version_id)
    prompt_context = await load_prompt_context(session, run.project_id)
    return {
        "run_id": run.id,
        "project_id": run.project_id,
        "requirement_id": run.requirement_id,
        "requirement_version_id": run.requirement_version_id,
        "raw_requirement": version.content if version else "",
        "agents_md": prompt_context["agents_md"],
        "skill_index": prompt_context["skill_index"],
        "gate_decisions": {},
        "revisions": {},
        "review_round": 0,
        "max_review_rounds": run.max_review_rounds,
        "focus_feedback": "",
    }


async def sync_requirement_status(session, run: PipelineRun, run_status: str) -> None:
    """把最新一次运行的状态同步回需求。

    只同步「当前 latest_run_id 指向的那次运行」，避免旧 run 的收尾把新 run 的状态覆盖掉。
    """
    requirement = await session.get(Requirement, run.requirement_id)
    if requirement is None or requirement.latest_run_id != run.id:
        return
    mapped = REQUIREMENT_STATUS_MAP.get(run_status)
    if mapped and requirement.status != mapped:
        requirement.status = mapped
        requirement.updated_at = utcnow()


async def execute_run(
    run_id: int,
    *,
    resume_payload: dict[str, Any] | None = None,
    continue_run: bool = False,
    event_logger: EventLogger | None = None,
    tools: list[Any] | None = None,
) -> None:
    """执行一次（或恢复一次）流水线。异常一律转成 run.status=failed，不往外抛。

    `tools` 只给测试注入用；正常路径由 `_execute` 按项目配置加载。
    """
    events = event_logger or EventLogger(run_id, publish=False)
    try:
        await _execute(run_id, resume_payload, continue_run, events, tools)
    finally:
        await events.close()


async def _execute(
    run_id: int,
    resume_payload: dict[str, Any] | None,
    continue_run: bool,
    events: EventLogger,
    tools: list[Any] | None = None,
) -> None:
    try:
        graph = await get_graph()
    except Exception as exc:
        logger.exception("checkpointer_unavailable")
        await _fail(run_id, "checkpointer_unavailable", str(exc), events)
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            logger.warning("run_not_found", extra={"run_id": run_id})
            return
        if run.status in {"succeeded", "failed", "cancelled"}:
            return

        config = graph_config(run)
        if resume_payload is not None:
            payload: Any = Command(resume=resume_payload)
        elif continue_run:
            payload = None
        else:
            try:
                assert_provider_ready()
            except ProviderNotConfigured as exc:
                await _fail(run_id, exc.code, exc.message, events)
                return
            payload = await _initial_state(session, run)

        run.status = "running"
        run.started_at = run.started_at or utcnow()
        run.updated_at = utcnow()
        await sync_requirement_status(session, run, "running")
        await session.commit()
        current_stage = run.current_stage

    await events.emit(
        "run_started",
        {
            "status": "running",
            "resumed": bool(resume_payload) or continue_run,
            "stage": current_stage,
        },
        stage=current_stage,
    )

    batcher = _TokenBatcher(events)
    resolved_tools = tools
    if resolved_tools is None:
        resolved_tools = await _load_tools(run, events)
    if resolved_tools:
        set_run_tools(run_id, resolved_tools)

    cancel_checked_at = 0.0
    try:
        async for mode, chunk in graph.astream(
            payload, config, stream_mode=["updates", "messages", "custom"]
        ):
            # 取消检查要查远程 MariaDB：messages 模式下每 chunk 都查会拖垮流式速度，
            # 所以节流到每 1 秒一次；updates（节点边界）永远检查。
            now = time.monotonic()
            if mode == "updates" or (now - cancel_checked_at) >= 1.0:
                cancel_checked_at = now
                if await _is_cancelled(run_id):
                    raise RunCancelled
            if mode == "messages":
                await _handle_message(batcher, chunk)
            elif mode == "custom":
                await _handle_custom(events, chunk)
            else:
                await _handle_chunk(run_id, graph, config, chunk, events, batcher)
    except RunCancelled:
        await batcher.flush_all()
        logger.info("run_cancelled", extra={"run_id": run_id})
        await events.emit("run_finished", {"status": "cancelled", "error_code": None}, stage=None)
        return
    except ProviderNotConfigured as exc:
        await batcher.flush_all()
        await _fail(run_id, exc.code, exc.message, events)
        return
    except Exception as exc:
        logger.exception("run_execution_failed", extra={"run_id": run_id})
        await batcher.flush_all()
        await _fail(run_id, "internal", f"{type(exc).__name__}: {exc}", events)
        return
    finally:
        clear_run_tools(run_id)
        clear_run_sandbox(run_id)

    await batcher.flush_all()
    await _finalize(run_id, graph, config, events)


TOOLS_LOAD_TIMEOUT = 25.0


async def _load_tools(run: PipelineRun, events: EventLogger) -> list[Any]:
    """加载 MCP / 技能工具，并在项目配了仓库时准备编码沙箱。失败一律降级不阻断。"""
    from app.agents.sandbox_tools import build_sandbox_tools
    from app.agents.tool_registry import set_run_sandbox
    from app.agents.tools import load_project_tools, tools_enabled

    tools: list[Any] = []
    if tools_enabled():
        try:
            async with get_session_factory()() as session:
                loaded, diagnostics = await asyncio.wait_for(
                    load_project_tools(session, run.project_id), timeout=TOOLS_LOAD_TIMEOUT
                )
            tools.extend(loaded)
            for item in diagnostics:
                if not item.get("ok"):
                    await events.emit(
                        "error",
                        {
                            "code": "mcp_tool_unavailable",
                            "message": f"{item.get('server')}: {item.get('error')}"[:500],
                        },
                        stage=None,
                    )
        except TimeoutError:
            logger.warning("tools_load_timeout", extra={"project_id": run.project_id})
            await events.emit(
                "error",
                {"code": "tools_load_timeout", "message": "工具加载超时，编码阶段将在无工具下运行"},
                stage=None,
            )
        except Exception as exc:
            logger.exception("tools_load_failed", extra={"project_id": run.project_id})
            await events.emit(
                "error",
                {"code": "tools_load_failed", "message": str(exc)[:500]},
                stage=None,
            )

    if get_settings().sandbox_enabled:
        try:
            workspace = await _prepare_sandbox(run)
            if workspace is not None:
                tools.extend(build_sandbox_tools(workspace))
                set_run_sandbox(run.id, workspace)
                await events.emit(
                    "progress",
                    {
                        "message": f"编码沙箱就绪：{workspace.branch}",
                        "workspace": str(workspace.root),
                    },
                    stage=None,
                )
        except Exception as exc:
            logger.exception("sandbox_prepare_failed", extra={"run_id": run.id})
            await events.emit(
                "error",
                {"code": "sandbox_unavailable", "message": str(exc)[:500]},
                stage=None,
            )
    return tools


async def _prepare_sandbox(run: PipelineRun):
    """按项目仓库配置准备 worktree；没配仓库返回 None。"""
    from app.core.security import decrypt_secret
    from app.models import Credential, Project
    from app.sandbox.worktree import prepare_workspace

    async with get_session_factory()() as session:
        project = await session.get(Project, run.project_id)
        if project is None or not project.repo_url:
            return None

        token: str | None = None
        if project.credential_id:
            credential = await session.get(Credential, project.credential_id)
            if credential is not None:
                token = decrypt_secret(credential.encrypted_blob, credential.key_version)

        branch = f"devpipeline/run-{run.id}"
        workspace = await prepare_workspace(
            run_id=run.id,
            repo_url=project.repo_url,
            base_branch=project.default_branch or "main",
            branch=branch,
            token=token,
        )

        row = (
            await session.execute(
                select(CodeWorkspace).where(
                    CodeWorkspace.run_id == run.id, CodeWorkspace.attempt == 1
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = CodeWorkspace(
                run_id=run.id,
                attempt=1,
                mode="worktree",
                repo_url=project.repo_url,
                workspace_path=str(workspace.root),
                branch=branch,
            )
            session.add(row)
        row.workspace_path = str(workspace.root)
        row.branch = branch
        # 复用目录时 base_sha 为空（clone 阶段才有）：别把已有的 base/head 覆盖成空
        row.base_sha = workspace.base_sha or row.base_sha
        row.head_sha = await workspace.head() or row.head_sha
        row.repo_url = project.repo_url
        await session.commit()
        return workspace


async def _handle_custom(events: EventLogger, chunk: Any) -> None:
    """节点用 get_stream_writer() 推来的自定义事件。

    目前有工具调用、PR 交付，以及节点内的降级 error（如 pr_unavailable）。
    """
    if not isinstance(chunk, dict):
        return
    event_type = str(chunk.get("type") or "")
    if event_type not in {"tool_started", "tool_finished", "pull_request_created", "error"}:
        return
    payload = chunk.get("payload") or {}
    stage = chunk.get("stage")
    await events.emit(event_type, payload, stage=str(stage) if stage else None)


async def _handle_message(batcher: _TokenBatcher, chunk: Any) -> None:
    """messages 模式的 chunk 形状是 (message_chunk, metadata)。"""
    try:
        message_chunk, metadata = chunk
    except (TypeError, ValueError):
        return
    text = getattr(message_chunk, "content", "")
    if not isinstance(text, str) or not text:
        return
    node = (metadata or {}).get("langgraph_node")
    # metadata 里是 langgraph 节点名（analyze_requirement…），必须换成阶段枚举再发事件
    stage = NODE_TO_STAGE.get(node) if isinstance(node, str) else None
    if stage is None:
        return
    await batcher.add(stage, text)


async def _handle_chunk(
    run_id: int,
    graph,
    config: dict,
    chunk: dict[str, Any],
    events: EventLogger,
    batcher: _TokenBatcher,
) -> None:
    if "__interrupt__" in chunk:
        interrupts = chunk["__interrupt__"]
        payload = getattr(interrupts[0], "value", None) if interrupts else None
        await batcher.flush_all()
        await _mark_waiting(run_id, graph, config, payload or {}, events)
        return

    for node, update in (chunk or {}).items():
        outcome = (update or {}).get("last_stage")
        if not outcome:
            continue
        await batcher.flush(outcome.get("stage"))
        # gate 节点只在「改后通过」时产生产物：只落 artifact，不覆盖 stage_runs 的耗时与用量
        await _persist_stage(
            run_id, outcome, events, stage_row=not node.startswith("gate_")
        )


async def _is_cancelled(run_id: int) -> bool:
    async with get_session_factory()() as session:
        status = await session.scalar(
            select(PipelineRun.status).where(PipelineRun.id == run_id)
        )
    return status == "cancelled"


async def _persist_stage(
    run_id: int, outcome: dict[str, Any], events: EventLogger, *, stage_row: bool = True
) -> None:
    stage = str(outcome.get("stage") or "")
    if not stage:
        return
    attempt = int(outcome.get("attempt") or 1)
    usage = outcome.get("usage") or {}
    started = _parse_iso(outcome.get("started_at")) or utcnow()
    finished = _parse_iso(outcome.get("finished_at")) or utcnow()
    duration_ms = max(0, int((finished - started).total_seconds() * 1000))
    settings = get_settings()
    artifact_saved: dict[str, Any] | None = None
    duration_for_event = duration_ms

    async with get_session_factory()() as session:
        if stage_row:
            stmt = select(StageRun).where(
                StageRun.run_id == run_id, StageRun.stage == stage, StageRun.attempt == attempt
            )
            stage_run = (await session.execute(stmt)).scalar_one_or_none()
            if stage_run is None:
                stage_run = StageRun(run_id=run_id, stage=stage, attempt=attempt)
                session.add(stage_run)
            stage_run.status = "succeeded"
            stage_run.provider = settings.llm_provider_name
            stage_run.model = settings.llm_model
            stage_run.prompt_tokens = usage.get("prompt_tokens")
            stage_run.completion_tokens = usage.get("completion_tokens")
            stage_run.duration_ms = duration_ms
            stage_run.started_at = started
            stage_run.finished_at = finished

        artifact = outcome.get("artifact") or {}
        if artifact.get("content"):
            version = await _next_artifact_version(session, run_id, stage)
            row = Artifact(
                run_id=run_id,
                stage=stage,
                version=version,
                kind=str(artifact.get("kind") or "markdown"),
                content=str(artifact["content"]),
                summary=(str(artifact.get("summary") or ""))[:1024] or None,
                edited_by_human=bool(artifact.get("edited_by_human")),
            )
            session.add(row)
            await session.flush()
            artifact_saved = {
                "artifact_id": row.id,
                "stage": stage,
                "version": version,
                "kind": row.kind,
                "summary": row.summary,
                "edited_by_human": row.edited_by_human,
            }

        run = await session.get(PipelineRun, run_id)
        if run is not None:
            run.current_stage = stage
            run.updated_at = utcnow()
        try:
            await session.commit()
        except IntegrityError:
            # 同一 run 理论上只有一个执行器；撞唯一键说明重复投递，丢弃即可
            await session.rollback()
            logger.warning("stage_persist_conflict", extra={"run_id": run_id, "stage": stage})
            return

    if stage_row:
        await events.emit(
            "usage",
            {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
            stage=stage,
        )
    if artifact_saved:
        await events.emit("artifact_saved", artifact_saved, stage=stage)
    if stage_row:
        await events.emit(
            "stage_finished",
            {"stage": stage, "attempt": attempt, "duration_ms": duration_for_event},
            stage=stage,
        )


async def _next_artifact_version(session, run_id: int, stage: str) -> int:
    stmt = select(Artifact.version).where(Artifact.run_id == run_id, Artifact.stage == stage)
    versions = [row[0] for row in (await session.execute(stmt)).all()]
    return (max(versions) + 1) if versions else 1


async def _mark_waiting(
    run_id: int, graph, config: dict, payload: dict[str, Any], events: EventLogger
) -> None:
    snapshot = await graph.aget_state(config)
    checkpoint_id = _checkpoint_id(snapshot)
    async with get_session_factory()() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            return
        run.status = "waiting_approval"
        run.current_stage = str(payload.get("stage") or run.current_stage or "")
        run.last_checkpoint_id = checkpoint_id or run.last_checkpoint_id
        # 图状态是权威：把回退轮次同步回业务库
        run.review_round = int((snapshot.values or {}).get("review_round") or 0)
        run.updated_at = utcnow()
        await sync_requirement_status(session, run, run.status)
        await session.commit()
    await events.emit(
        "interrupt",
        {
            "stage": payload.get("stage"),
            "label": payload.get("label"),
            "attempt": payload.get("attempt"),
            "summary": payload.get("summary"),
            "checkpoint_id": checkpoint_id,
        },
        stage=payload.get("stage"),
    )
    logger.info("run_waiting_approval", extra={"run_id": run_id, "stage": payload.get("stage")})


def _checkpoint_id(snapshot: Any) -> str | None:
    try:
        return str(snapshot.config["configurable"]["checkpoint_id"])
    except (KeyError, TypeError):
        return None


async def _finalize(run_id: int, graph, config: dict, events: EventLogger) -> None:
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}
    checkpoint_id = _checkpoint_id(snapshot)
    status = "running"
    error_code: str | None = None

    async with get_session_factory()() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            return
        if run.status == "cancelled":
            return
        run.last_checkpoint_id = checkpoint_id or run.last_checkpoint_id
        error_code = str(values.get("error") or "") or None
        run.review_round = int(values.get("review_round") or run.review_round or 0)

        if getattr(snapshot, "interrupts", None):
            run.status = "waiting_approval"
        elif error_code:
            run.status = "failed"
            run.error_code = error_code
            run.error_message = ERROR_MESSAGES.get(error_code, error_code)
            run.finished_at = utcnow()
        elif getattr(snapshot, "next", None):
            # 还有待执行节点却没被流消费完：保持 running，交给下一次续跑
            run.status = "running"
        else:
            run.status = "succeeded"
            run.finished_at = utcnow()
        run.reconciled_at = utcnow()
        await sync_requirement_status(session, run, run.status)
        status = run.status
        await session.commit()

    if status == "waiting_approval":
        # 等人工审批不是结束：只有 interrupt 事件，不发 run_finished（否则前端会关掉连接）
        return
    if status == "failed" and error_code:
        await events.emit(
            "error",
            {"code": error_code, "message": ERROR_MESSAGES.get(error_code, error_code)},
            stage=None,
        )
    await events.emit("run_finished", {"status": status, "error_code": error_code}, stage=None)


async def _fail(run_id: int, code: str, message: str, events: EventLogger) -> None:
    async with get_session_factory()() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.error_code = code
        run.error_message = message[:2000]
        run.finished_at = utcnow()
        run.updated_at = utcnow()
        await sync_requirement_status(session, run, "failed")
        await session.commit()
    await events.emit("error", {"code": code, "message": message[:2000]}, stage=None)
    await events.emit("run_finished", {"status": "failed", "error_code": code}, stage=None)

