from __future__ import annotations

import asyncio
from typing import Self

import pytest

from app.models import RunEvent
from app.services import events as events_module
from app.services.events import EventLogger


class _FakeSession:
    def __init__(self, store: list[list[RunEvent]], gate: asyncio.Event | None) -> None:
        self.store = store
        self.gate = gate
        self.rows: list[RunEvent] = []

    def add_all(self, rows) -> None:
        self.rows = list(rows)

    async def commit(self) -> None:
        if self.gate is not None:
            gate, self.gate = self.gate, None
            await gate.wait()  # 第一次 commit 卡住，模拟在途 flush
        self.store.append(self.rows)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args) -> None:
        return None


def _row(seq: int) -> RunEvent:
    return RunEvent(run_id=1, seq=seq, stage="analysis", type="llm_token", payload="{}")


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch):
    async def _next_seq(self: EventLogger) -> int:
        self._local_seq = (self._local_seq or 0) + 1
        return self._local_seq

    monkeypatch.setattr(EventLogger, "_next_seq", _next_seq)


async def test_cancelled_flush_requeues_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭时取消在途 flush，不能丢事件（回归：实测会丢 interrupt）。"""
    store: list[list[RunEvent]] = []
    gate = asyncio.Event()
    sessions = iter([_FakeSession(store, gate), _FakeSession(store, None)])

    def factory():
        return next(sessions)

    monkeypatch.setattr(events_module, "get_session_factory", lambda: factory)

    logger = EventLogger(1, publish=False)
    logger._buffer = [_row(1)]
    inflight = asyncio.create_task(logger.flush())
    logger._flush_task = inflight  # 模拟后台 flush 任务
    await asyncio.sleep(0)  # 让 flush 走到 commit 并挂起

    logger._buffer.append(_row(2))  # 在途期间又来了一个事件
    gate.set()
    await logger.close()

    written = sorted(row.seq for batch in store for row in batch)
    assert written == [1, 2]
    inflight.cancel()


async def test_close_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    store: list[list[RunEvent]] = []
    monkeypatch.setattr(
        events_module, "get_session_factory", lambda: lambda: _FakeSession(store, None)
    )
    logger = EventLogger(1, publish=False)
    logger._buffer = [_row(1)]
    await logger.close()
    await logger.close()
    assert [row.seq for batch in store for row in batch] == [1]
