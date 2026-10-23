from __future__ import annotations

import json

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.v1.deps import PaginationDep, SessionDep
from app.models import CodeWorkspace, PullRequest
from app.schemas.common import Page
from app.schemas.run import (
    ApprovalIn,
    ApprovalOut,
    EventOut,
    PendingApproval,
    PullRequestOut,
    RunCreate,
    RunDetail,
    RunOut,
    StateSummary,
    WorkspaceCleanupOut,
    WorkspaceOut,
)
from app.services import run_service, workspace_service

router = APIRouter(tags=["runs"])


def _run_out(run, prompt_tokens: int = 0, completion_tokens: int = 0) -> RunOut:
    out = RunOut.model_validate(run)
    out.prompt_tokens = prompt_tokens
    out.completion_tokens = completion_tokens
    return out


@router.post(
    "/requirements/{requirement_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
    summary="启动流水线（后台执行，停在第一个审批门）",
)
async def create_run(session: SessionDep, requirement_id: int, payload: RunCreate | None = None) -> RunOut:
    run = await run_service.create_run(session, requirement_id, payload or RunCreate())
    return _run_out(run)


@router.get("/runs", response_model=Page[RunOut], summary="运行列表")
async def list_runs(
    session: SessionDep,
    pag: PaginationDep,
    project_id: int | None = Query(default=None),
    requirement_id: int | None = Query(default=None),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(queued|running|waiting_approval|succeeded|failed|cancelled)$",
    ),
) -> Page[RunOut]:
    rows, total = await run_service.list_runs(
        session,
        page=pag.page,
        page_size=pag.page_size,
        project_id=project_id,
        requirement_id=requirement_id,
        status=status_filter,
    )
    return Page[RunOut](
        items=[_run_out(run, p, c) for run, p, c in rows],
        total=total,
        page=pag.page,
        page_size=pag.page_size,
    )


@router.get("/runs/{run_id}", response_model=RunDetail, summary="运行详情（含待审批摘要）")
async def get_run(session: SessionDep, run_id: int) -> RunDetail:
    run = await run_service.get_run(session, run_id)
    prompt, completion = await run_service.run_usage(session, run.id)
    pending = await run_service.pending_approval(session, run)
    detail = RunDetail.model_validate(run)
    detail.prompt_tokens = prompt
    detail.completion_tokens = completion
    detail.pending_approval = PendingApproval(**pending) if pending else None
    return detail


@router.get(
    "/runs/{run_id}/workspaces",
    response_model=list[WorkspaceOut],
    summary="编码沙箱工作区（worktree 路径与分支）",
)
async def list_workspaces(session: SessionDep, run_id: int) -> list[WorkspaceOut]:
    await run_service.get_run(session, run_id, reconcile=False)
    rows = (
        (
            await session.execute(
                select(CodeWorkspace)
                .where(CodeWorkspace.run_id == run_id)
                .order_by(CodeWorkspace.attempt)
            )
        )
        .scalars()
        .all()
    )
    return [WorkspaceOut.model_validate(row) for row in rows]


@router.delete(
    "/runs/{run_id}/workspaces",
    response_model=WorkspaceCleanupOut,
    summary="清理该运行的沙箱工作区（只允许终态运行）",
)
async def cleanup_workspaces(session: SessionDep, run_id: int) -> WorkspaceCleanupOut:
    await run_service.get_run(session, run_id, reconcile=False)
    removed = await workspace_service.cleanup_run_workspaces(run_id)
    return WorkspaceCleanupOut(removed=len(removed))


@router.get(
    "/runs/{run_id}/pull-requests",
    response_model=list[PullRequestOut],
    summary="运行创建的 PR（provider/number/url/status）",
)
async def list_pull_requests(session: SessionDep, run_id: int) -> list[PullRequestOut]:
    await run_service.get_run(session, run_id, reconcile=False)
    rows = (
        (
            await session.execute(
                select(PullRequest)
                .where(PullRequest.run_id == run_id)
                .order_by(PullRequest.id)
            )
        )
        .scalars()
        .all()
    )
    return [PullRequestOut.model_validate(row) for row in rows]


@router.get(
    "/runs/{run_id}/pending-approval",
    response_model=PendingApproval,
    responses={204: {"description": "当前没有待审批项"}},
    summary="当前待审批项（没有则 204）",
)
async def get_pending_approval(session: SessionDep, run_id: int):
    run = await run_service.get_run(session, run_id, reconcile=False)
    pending = await run_service.pending_approval(session, run)
    if pending is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return PendingApproval(**pending)


@router.post(
    "/runs/{run_id}/approval",
    response_model=ApprovalOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交审批决策（通过 / 改后通过 / 驳回 / 中止）",
)
async def decide(session: SessionDep, run_id: int, payload: ApprovalIn) -> ApprovalOut:
    approval = await run_service.decide(session, run_id, payload)
    return ApprovalOut.model_validate(approval)


@router.get(
    "/runs/{run_id}/states",
    response_model=list[StateSummary],
    summary="checkpoint 状态历史（aget_state_history）",
)
async def list_states(
    session: SessionDep,
    run_id: int,
    limit: int = Query(default=20, ge=1, le=50),
) -> list[StateSummary]:
    run = await run_service.get_run(session, run_id, reconcile=False)
    items = await run_service.list_states(run, limit=limit)
    return [StateSummary(**item) for item in items]


@router.get(
    "/runs/{run_id}/events",
    response_model=list[EventOut],
    summary="事件历史（after_seq 游标，SSE 断线后可补齐）",
)
async def list_events(
    session: SessionDep,
    run_id: int,
    after_seq: int = Query(default=0, ge=0),
    page_size: int = Query(default=200, ge=1, le=1000),
    types: str | None = Query(default=None, description="逗号分隔的事件类型过滤"),
) -> list[EventOut]:
    await run_service.get_run(session, run_id, reconcile=False)
    type_list = [item.strip() for item in types.split(",") if item.strip()] if types else None
    rows = await run_service.list_events(
        session, run_id, after_seq=after_seq, page_size=page_size, types=type_list
    )
    return [
        EventOut(
            seq=row.seq,
            ts=row.created_at,
            stage=row.stage,
            type=row.type,
            payload=json.loads(row.payload or "{}"),
        )
        for row in rows
    ]


@router.post(
    "/runs/{run_id}/retry",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="失败重试（从最后 checkpoint 续跑；没有 key 时 422）",
)
async def retry_run(session: SessionDep, run_id: int) -> RunOut:
    run = await run_service.retry_run(session, run_id)
    prompt, completion = await run_service.run_usage(session, run.id)
    return _run_out(run, prompt, completion)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunOut,
    summary="取消运行（等待审批时立即生效；运行中在下一个节点边界生效）",
)
async def cancel_run(session: SessionDep, run_id: int) -> RunOut:
    run = await run_service.cancel_run(session, run_id)
    prompt, completion = await run_service.run_usage(session, run.id)
    return _run_out(run, prompt, completion)


__all__ = ["router"]
