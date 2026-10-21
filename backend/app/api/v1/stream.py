"""运行事件流：SSE 实时推送 + Last-Event-ID 回放。

两段式：
1. 先按 `last_event_id` 从 `run_events` 回放（断线重连/新开标签页都能补齐）；
2. 再订阅 Redis `run:{id}:events` 继续推，`seq` 去重，收到 `run_finished` 主动关闭。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.core.exceptions import NotFoundError
from app.db.session import get_session_factory
from app.models import PipelineRun
from app.services import run_service
from app.services.events import EVENT_CHANNEL, get_redis

router = APIRouter(tags=["stream"])

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
REPLAY_PAGE = 200


@router.get(
    "/runs/{run_id}/stream",
    summary="运行事件流（SSE，支持 Last-Event-ID 断线续传）",
    response_class=EventSourceResponse,
)
async def stream_run(
    run_id: int,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after_seq: int = Query(default=0, ge=0, alias="last_event_id"),
):
    async with get_session_factory()() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            raise NotFoundError("运行不存在")
        status = run.status

    try:
        cursor = max(int(last_event_id), after_seq) if last_event_id else after_seq
    except ValueError:
        cursor = after_seq

    async def _gen():
        nonlocal cursor
        saw_finished = False

        # 1) 回放历史
        while True:
            async with get_session_factory()() as session:
                rows = await run_service.list_events(
                    session, run_id, after_seq=cursor, page_size=REPLAY_PAGE
                )
            if not rows:
                break
            for row in rows:
                cursor = max(cursor, row.seq)
                if row.type == "run_finished":
                    saw_finished = True
                yield {
                    "id": str(row.seq),
                    "event": row.type,
                    "data": row.payload,
                }
            if len(rows) < REPLAY_PAGE:
                break

        # 已结束且回放里没有终止事件（例如取消后进程重启）：补一条，客户端即可断开
        if status in TERMINAL_STATUSES and not saw_finished:
            yield {
                "id": str(cursor),
                "event": "run_finished",
                "data": json.dumps({"status": status}, ensure_ascii=False),
            }
            return

        # 2) 实时订阅
        redis = await get_redis()
        pubsub = redis.pubsub()
        channel = EVENT_CHANNEL.format(run_id=run_id)
        await pubsub.subscribe(channel)
        try:
            idle_ticks = 0
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    idle_ticks += 1
                    if idle_ticks % 10 == 0:
                        # 兜底：状态已终态但没收到事件（例如 worker 崩溃后取消）
                        async with get_session_factory()() as session:
                            current = await session.scalar(
                                select(PipelineRun.status).where(PipelineRun.id == run_id)
                            )
                        if current in TERMINAL_STATUSES:
                            yield {
                                "id": str(cursor),
                                "event": "run_finished",
                                "data": json.dumps({"status": current}, ensure_ascii=False),
                            }
                            break
                    continue

                idle_ticks = 0
                envelope = json.loads(message["data"])
                if envelope["seq"] <= cursor:
                    continue
                cursor = envelope["seq"]
                yield {
                    "id": str(cursor),
                    "event": envelope["type"],
                    "data": json.dumps(envelope["payload"], ensure_ascii=False),
                }
                if envelope["type"] == "run_finished":
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return EventSourceResponse(
        _gen(),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
