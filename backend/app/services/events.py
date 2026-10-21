from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models import RunEvent

logger = get_logger(__name__)

_client: aioredis.Redis | None = None
_lock = asyncio.Lock()

EVENT_CHANNEL = "run:{run_id}:events"
SEQ_KEY = "run:{run_id}:seq"


async def get_redis() -> aioredis.Redis:
    global _client
    if _client is not None:
        return _client
    async with _lock:
        if _client is None:
            _client = aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class EventLogger:
    """事件出口：Redis pub/sub 实时广播 + MariaDB 批量落库（回放用）。

    两边都写的原因：实时性靠 pub/sub，断线回放靠 run_events。
    seq 在 publish 模式走 Redis INCR（worker 与 api 不同进程也能单调）；
    测试/无 Redis 场景走 `publish=False`，从库里已有最大 seq 续号。
    """

    def __init__(
        self,
        run_id: int,
        *,
        publish: bool = True,
        flush_interval: float = 0.2,
        flush_size: int = 50,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        self.run_id = run_id
        self._publish = publish
        self._interval = flush_interval
        self._size = flush_size
        self._buffer: list[RunEvent] = []
        self._redis = redis_client
        self._flush_task: asyncio.Task | None = None
        self._local_seq: int | None = None
        self._redis_broken = False
        self._closed = False

    async def _client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    async def _next_seq(self) -> int:
        """seq 必须全局单调：优先 Redis INCR；Redis 不可用时退化为「库里最大值 +1」。

        退化路径只保证单执行器正确（跨进程并发时可能撞唯一键，由批量落库的重试/日志兜底），
        用来保证「Redis 挂了流水线还能跑」，不是正常路径。
        """
        if not self._redis_broken:
            try:
                client = await self._client()
                return int(await client.incr(SEQ_KEY.format(run_id=self.run_id)))
            except Exception:  # noqa: BLE001
                self._redis_broken = True
                logger.warning("event_seq_redis_down", extra={"run_id": self.run_id})

        if self._local_seq is None:
            async with get_session_factory()() as session:
                self._local_seq = int(
                    (
                        await session.execute(
                            select(func.coalesce(func.max(RunEvent.seq), 0)).where(
                                RunEvent.run_id == self.run_id
                            )
                        )
                    ).scalar_one()
                )
        self._local_seq += 1
        return self._local_seq

    async def emit(self, event_type: str, payload: dict[str, Any], *, stage: str | None = None) -> dict:
        seq = await self._next_seq()
        envelope = {
            "seq": seq,
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "run_id": self.run_id,
            "stage": stage,
            "type": event_type,
            "payload": payload,
        }
        if self._publish:
            # 广播失败不能让流水线挂掉：库里还有，SSE 能回放
            try:
                client = await self._client()
                await client.publish(
                    EVENT_CHANNEL.format(run_id=self.run_id), _json(envelope)
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "event_publish_failed", extra={"run_id": self.run_id, "type": event_type}
                )
        self._buffer.append(
            RunEvent(
                run_id=self.run_id,
                seq=seq,
                stage=stage,
                type=event_type,
                payload=_json(payload),
            )
        )
        if len(self._buffer) >= self._size:
            await self.flush()
        else:
            self._ensure_flush_task()
        return envelope

    def _ensure_flush_task(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            return
        self._flush_task = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        try:
            await asyncio.sleep(self._interval)
            await self.flush()
        except asyncio.CancelledError:  # pragma: no cover - 关闭时取消
            raise
        except Exception:
            logger.exception("event_flush_failed", extra={"run_id": self.run_id})

    async def flush(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        try:
            async with get_session_factory()() as session:
                session.add_all(batch)
                await session.commit()
        except Exception:
            logger.exception(
                "event_persist_failed", extra={"run_id": self.run_id, "count": len(batch)}
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._flush_task is not None:
            self._flush_task.cancel()
            self._flush_task = None
        await self.flush()
