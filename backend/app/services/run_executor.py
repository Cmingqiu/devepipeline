"""执行器：把图跑起来，并把 `last_stage` / interrupt 落成 MariaDB 记录。

输入/恢复三种形态：
- `start`     首次执行，传初始 state；
- `continue_run`  进程重启后从最后一个 checkpoint 续跑（input=None）；
- `resume_payload`  人工审批后 `Command(resume=...)`。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.graph import build_graph
from app.agents.llm import ProviderNotConfigured, assert_provider_ready
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.graph_db import get_checkpointer
from app.db.session import get_session_factory
from app.models import Artifact, PipelineRun, Requirement, RequirementVersion, StageRun

logger = get_logger(__name__)

_compiled_graph = None

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
    return {
        "run_id": run.id,
        "project_id": run.project_id,
        "requirement_id": run.requirement_id,
        "requirement_version_id": run.requirement_version_id,
        "raw_requirement": version.content if version else "",
        "agents_md": "",
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
) -> None:
    """执行一次（或恢复一次）流水线。异常一律转成 run.status=failed，不往外抛。"""
    try:
        graph = await get_graph()
    except Exception as exc:
        logger.exception("checkpointer_unavailable")
        await _fail(run_id, "checkpointer_unavailable", str(exc))
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
                await _fail(run_id, exc.code, exc.message)
                return
            payload = await _initial_state(session, run)

        run.status = "running"
        run.started_at = run.started_at or utcnow()
        run.updated_at = utcnow()
        await sync_requirement_status(session, run, "running")
        await session.commit()

    try:
        async for chunk in graph.astream(payload, config, stream_mode="updates"):
            await _handle_chunk(run_id, graph, config, chunk)
    except RunCancelled:
        logger.info("run_cancelled", extra={"run_id": run_id})
        return
    except ProviderNotConfigured as exc:
        await _fail(run_id, exc.code, exc.message)
        return
    except Exception as exc:
        logger.exception("run_execution_failed", extra={"run_id": run_id})
        await _fail(run_id, "internal", f"{type(exc).__name__}: {exc}")
        return

    await _finalize(run_id, graph, config)


async def _handle_chunk(run_id: int, graph, config: dict, chunk: dict[str, Any]) -> None:
    if await _is_cancelled(run_id):
        raise RunCancelled
    if "__interrupt__" in chunk:
        interrupts = chunk["__interrupt__"]
        payload = getattr(interrupts[0], "value", None) if interrupts else None
        await _mark_waiting(run_id, graph, config, payload or {})
        return

    for node, update in (chunk or {}).items():
        outcome = (update or {}).get("last_stage")
        if not outcome:
            continue
        # gate 节点只在「改后通过」时产生产物：只落 artifact，不覆盖 stage_runs 的耗时与用量
        await _persist_stage(run_id, outcome, stage_row=not node.startswith("gate_"))


async def _is_cancelled(run_id: int) -> bool:
    async with get_session_factory()() as session:
        status = await session.scalar(
            select(PipelineRun.status).where(PipelineRun.id == run_id)
        )
    return status == "cancelled"


async def _persist_stage(run_id: int, outcome: dict[str, Any], *, stage_row: bool = True) -> None:
    stage = str(outcome.get("stage") or "")
    if not stage:
        return
    attempt = int(outcome.get("attempt") or 1)
    usage = outcome.get("usage") or {}
    started = _parse_iso(outcome.get("started_at")) or utcnow()
    finished = _parse_iso(outcome.get("finished_at")) or utcnow()
    settings = get_settings()

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
            stage_run.duration_ms = max(0, int((finished - started).total_seconds() * 1000))
            stage_run.started_at = started
            stage_run.finished_at = finished

        artifact = outcome.get("artifact") or {}
        if artifact.get("content"):
            version = await _next_artifact_version(session, run_id, stage)
            session.add(
                Artifact(
                    run_id=run_id,
                    stage=stage,
                    version=version,
                    kind=str(artifact.get("kind") or "markdown"),
                    content=str(artifact["content"]),
                    summary=(str(artifact.get("summary") or ""))[:1024] or None,
                    edited_by_human=bool(artifact.get("edited_by_human")),
                )
            )

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


async def _next_artifact_version(session, run_id: int, stage: str) -> int:
    stmt = select(Artifact.version).where(Artifact.run_id == run_id, Artifact.stage == stage)
    versions = [row[0] for row in (await session.execute(stmt)).all()]
    return (max(versions) + 1) if versions else 1


async def _mark_waiting(run_id: int, graph, config: dict, payload: dict[str, Any]) -> None:
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
    logger.info("run_waiting_approval", extra={"run_id": run_id, "stage": payload.get("stage")})


def _checkpoint_id(snapshot: Any) -> str | None:
    try:
        return str(snapshot.config["configurable"]["checkpoint_id"])
    except (KeyError, TypeError):
        return None


async def _finalize(run_id: int, graph, config: dict) -> None:
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}
    checkpoint_id = _checkpoint_id(snapshot)

    async with get_session_factory()() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            return
        if run.status == "cancelled":
            return
        run.last_checkpoint_id = checkpoint_id or run.last_checkpoint_id
        error_code = str(values.get("error") or "")
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
        await session.commit()


async def _fail(run_id: int, code: str, message: str) -> None:
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

