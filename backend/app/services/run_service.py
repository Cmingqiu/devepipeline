from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import assert_provider_ready
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.session import get_session_factory
from app.models import Artifact, PipelineRun, Requirement, RequirementVersion, StageApproval, StageRun
from app.queue import inline

logger = get_logger(__name__)


def _checkpoint_id(snapshot: Any) -> str | None:
    try:
        return str(snapshot.config["configurable"]["checkpoint_id"])
    except (KeyError, TypeError):
        return None


def _snapshot_time(snapshot: Any) -> datetime | None:
    raw = getattr(snapshot, "created_at", None)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


async def _interrupt_already_decided(
    session: AsyncSession, run: PipelineRun, snapshot: Any, stage: str
) -> bool:
    """审批已提交、但 resume 还没被消费时，checkpoint 里仍是旧 interrupt。

    这一刻必须把 run 视为 running，且不再暴露待审批（否则 UI 会重复提交、读接口把状态倒回等待审批）。
    """
    decided_at = (
        await session.execute(
            select(StageApproval.decided_at)
            .where(StageApproval.run_id == run.id, StageApproval.stage == stage)
            .order_by(StageApproval.decided_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if decided_at is None:
        return False
    snapshot_time = _snapshot_time(snapshot)
    return snapshot_time is None or decided_at > snapshot_time


async def _graph_and_snapshot(run: PipelineRun):
    from app.services.run_executor import get_graph, graph_config

    graph = await get_graph()
    snapshot = await graph.aget_state(graph_config(run))
    return graph, snapshot


async def create_run(
    session: AsyncSession, requirement_id: int, payload, *, enqueue: bool = True
) -> PipelineRun:
    requirement = await session.get(Requirement, requirement_id)
    if requirement is None:
        raise NotFoundError("需求不存在")

    version_no = payload.version_no or requirement.current_version_no
    version = (
        await session.execute(
            select(RequirementVersion)
            .where(
                RequirementVersion.requirement_id == requirement_id,
                RequirementVersion.version_no == version_no,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"需求版本 v{version_no} 不存在")

    # 没有 key 时直接 422，不要跑到一半才失败
    assert_provider_ready()

    run = PipelineRun(
        project_id=requirement.project_id,
        requirement_id=requirement.id,
        requirement_version_id=version.id,
        thread_id=str(uuid4()),
        status="queued",
        max_review_rounds=payload.max_review_rounds,
    )
    session.add(run)
    await session.flush()
    requirement.latest_run_id = run.id
    requirement.status = "queued"
    await session.commit()

    if enqueue:
        from app.services.run_executor import execute_run

        inline.submit(execute_run(run.id), name=f"run-{run.id}")
    return run


async def list_runs(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    project_id: int | None = None,
    requirement_id: int | None = None,
    status: str | None = None,
) -> tuple[list[tuple[PipelineRun, int, int]], int]:
    filters = []
    if project_id is not None:
        filters.append(PipelineRun.project_id == project_id)
    if requirement_id is not None:
        filters.append(PipelineRun.requirement_id == requirement_id)
    if status:
        filters.append(PipelineRun.status == status)

    total = (
        await session.execute(select(func.count()).select_from(PipelineRun).where(*filters))
    ).scalar_one()

    stmt = (
        select(
            PipelineRun,
            func.coalesce(func.sum(StageRun.prompt_tokens), 0),
            func.coalesce(func.sum(StageRun.completion_tokens), 0),
        )
        .outerjoin(StageRun, StageRun.run_id == PipelineRun.id)
        .where(*filters)
        .group_by(PipelineRun.id)
        .order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await session.execute(stmt)).all()
    return [(run, int(p), int(c)) for run, p, c in rows], int(total)


async def get_run(session: AsyncSession, run_id: int, *, reconcile: bool = True) -> PipelineRun:
    run = await session.get(PipelineRun, run_id)
    if run is None:
        raise NotFoundError("运行不存在")
    if reconcile:
        await reconcile_run(session, run)
    return run


async def run_usage(session: AsyncSession, run_id: int) -> tuple[int, int]:
    stmt = select(
        func.coalesce(func.sum(StageRun.prompt_tokens), 0),
        func.coalesce(func.sum(StageRun.completion_tokens), 0),
    ).where(StageRun.run_id == run_id)
    prompt, completion = (await session.execute(stmt)).one()
    return int(prompt), int(completion)


async def latest_artifact_id(session: AsyncSession, run_id: int, stage: str | None) -> int | None:
    if not stage:
        return None
    stmt = (
        select(Artifact.id)
        .where(Artifact.run_id == run_id, Artifact.stage == stage)
        .order_by(Artifact.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def pending_approval(session: AsyncSession, run: PipelineRun) -> dict[str, Any] | None:
    """以图状态为准：有 interrupt 才有待审批，不看 MariaDB 的 status。"""
    try:
        _, snapshot = await _graph_and_snapshot(run)
    except Exception:  # noqa: BLE001  checkpointer 不可用时按“无待审批”处理
        return None
    interrupts = getattr(snapshot, "interrupts", None)
    if not interrupts:
        return None
    payload = dict(getattr(interrupts[0], "value", None) or {})
    stage = str(payload.get("stage") or "")
    if stage and await _interrupt_already_decided(session, run, snapshot, stage):
        return None
    payload["artifact_id"] = await latest_artifact_id(session, run.id, payload.get("stage"))
    payload["checkpoint_id"] = _checkpoint_id(snapshot)
    return payload


async def decide(
    session: AsyncSession, run_id: int, payload, *, enqueue: bool = True
) -> StageApproval:
    run = await session.get(PipelineRun, run_id)
    if run is None:
        raise NotFoundError("运行不存在")

    pending = await pending_approval(session, run)
    if pending is None:
        raise ConflictError("当前没有待审批项（运行可能不在等待审批状态）")

    approval = StageApproval(
        run_id=run.id,
        stage=str(pending.get("stage") or ""),
        artifact_id=pending.get("artifact_id"),
        decision=payload.decision,
        feedback=payload.feedback,
        decided_by="local",
    )
    session.add(approval)
    run.status = "running"
    run.updated_at = utcnow()
    await session.commit()

    if enqueue:
        from app.services.run_executor import execute_run

        inline.submit(
            execute_run(
                run.id,
                resume_payload=payload.model_dump(exclude_none=True),
            ),
            name=f"resume-{run.id}",
        )
    return approval


async def retry_run(session: AsyncSession, run_id: int) -> PipelineRun:
    """失败重试：只允许从失败的断点继续，不重头跑（避免覆盖既有产物）。"""
    run = await session.get(PipelineRun, run_id)
    if run is None:
        raise NotFoundError("运行不存在")
    if run.status not in {"failed", "cancelled"}:
        raise ConflictError("只有 failed / cancelled 的运行可以重试")

    from app.services.run_executor import execute_run, get_graph, graph_config

    graph = await get_graph()
    snapshot = await graph.aget_state(graph_config(run))
    if not getattr(snapshot, "next", None):
        raise ConflictError("该运行已走到终点，没有可继续的断点；请重新启动一次运行")

    assert_provider_ready()
    run.status = "running"
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    run.updated_at = utcnow()
    await session.commit()
    inline.submit(execute_run(run.id, continue_run=True), name=f"retry-{run.id}")
    return run


async def cancel_run(session: AsyncSession, run_id: int) -> PipelineRun:
    """取消：写库后执行器在下一个节点边界检测到并停止（进程内队列无法强杀协程）。"""
    run = await session.get(PipelineRun, run_id)
    if run is None:
        raise NotFoundError("运行不存在")
    if run.status in {"succeeded", "failed", "cancelled"}:
        return run
    run.status = "cancelled"
    run.finished_at = utcnow()
    run.updated_at = utcnow()
    await session.commit()
    return run


async def list_states(run: PipelineRun, *, limit: int = 20) -> list[dict[str, Any]]:
    from app.services.run_executor import get_graph, graph_config

    graph = await get_graph()
    history: list[dict[str, Any]] = []
    async for snapshot in graph.aget_state_history(graph_config(run), limit=limit):
        values = getattr(snapshot, "values", None) or {}
        last_stage = values.get("last_stage") or {}
        history.append(
            {
                "checkpoint_id": _checkpoint_id(snapshot),
                "stage": last_stage.get("stage") or run.current_stage,
                "next": list(getattr(snapshot, "next", None) or ()),
                "created_at": getattr(snapshot, "created_at", None),
                "has_interrupt": bool(getattr(snapshot, "interrupts", None)),
                "error": values.get("error"),
            }
        )
    return history


async def reconcile_run(session: AsyncSession, run: PipelineRun) -> PipelineRun:
    """以 LangGraph 状态为准修正 MariaDB 的 status / current_stage / last_checkpoint_id。"""
    if run.status in {"succeeded", "failed", "cancelled"}:
        return run
    try:
        _, snapshot = await _graph_and_snapshot(run)
    except Exception:  # noqa: BLE001  PG 不可用时不做校正，读接口不能因此 500
        return run

    values = getattr(snapshot, "values", None) or {}
    has_interrupt = bool(getattr(snapshot, "interrupts", None))
    has_next = bool(getattr(snapshot, "next", None))
    error = values.get("error")

    if has_interrupt:
        payload = getattr(snapshot.interrupts[0], "value", None) or {}
        stage = str(payload.get("stage") or run.current_stage or "")
        run.current_stage = stage or run.current_stage
        if stage and await _interrupt_already_decided(session, run, snapshot, stage):
            run.status = "running"  # 审批已提交，等 resume 消费
        else:
            run.status = "waiting_approval"
    elif has_next:
        if run.status == "waiting_approval":
            run.status = "running"
    elif values:
        run.status = "failed" if error else "succeeded"
        if error:
            run.error_code = str(error)
        run.finished_at = run.finished_at or utcnow()

    run.last_checkpoint_id = _checkpoint_id(snapshot) or run.last_checkpoint_id
    run.reconciled_at = utcnow()
    await session.commit()
    return run


async def requeue_incomplete() -> int:
    """启动时兜底：进程内队列随重启丢失，按 checkpoint 把未完成的 run 重新挂上。"""
    from app.services.run_executor import execute_run, get_graph, graph_config

    count = 0
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(PipelineRun)
                .where(PipelineRun.status.in_(["queued", "running"]))
                .order_by(PipelineRun.id)
                .limit(50)
            )
        ).scalars().all()

    for run in rows:
        try:
            graph = await get_graph()
            snapshot = await graph.aget_state(graph_config(run))
        except Exception as exc:  # noqa: BLE001  单个 run 读不到 checkpoint 不影响其它 run
            logger.warning(
                "requeue_state_read_failed", extra={"run_id": run.id, "error": str(exc)[:200]}
            )
            continue
        if getattr(snapshot, "interrupts", None):
            continue  # 等人工审批，不重跑
        if getattr(snapshot, "next", None):
            inline.submit(execute_run(run.id, continue_run=True), name=f"resume-{run.id}")
            count += 1
        elif not (snapshot.values or {}):
            inline.submit(execute_run(run.id), name=f"run-{run.id}")
            count += 1
    return count
