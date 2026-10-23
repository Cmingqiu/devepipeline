from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.queue import dispatcher, inline


@pytest.fixture(autouse=True)
def _arq_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "queue_backend", "arq", raising=False)


async def test_dispatcher_falls_back_to_inline_when_enqueue_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _healthy():
        return True

    async def _boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.queue.arq.worker_healthy", _healthy, raising=True)
    monkeypatch.setattr("app.queue.arq.enqueue_run", _boom, raising=True)

    backend = await dispatcher.enqueue_run(999999)
    assert backend == "inline"
    await inline.join()


async def test_dispatcher_falls_back_when_worker_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-10-23 的故障场景：worker 没起 → 不能把任务丢进空队列让 run 永远排队。"""

    async def _absent():
        return False

    async def _must_not_call(*args, **kwargs):
        raise AssertionError("worker 不在时不应该入 arq 队列")

    monkeypatch.setattr("app.queue.arq.worker_healthy", _absent, raising=True)
    monkeypatch.setattr("app.queue.arq.enqueue_run", _must_not_call, raising=True)

    backend = await dispatcher.enqueue_run(999998)
    assert backend == "inline"
    await inline.join()


async def test_dispatcher_ignores_duplicate_job(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _healthy():
        return True

    async def _duplicate(*args, **kwargs):
        return None  # arq 拒绝同 job_id

    monkeypatch.setattr("app.queue.arq.worker_healthy", _healthy, raising=True)
    monkeypatch.setattr("app.queue.arq.enqueue_run", _duplicate, raising=True)

    backend = await dispatcher.enqueue_run(999997)
    assert backend.startswith("arq:duplicate:run:999997:start")


def test_job_ids_are_deterministic() -> None:
    start = dispatcher.build_job_id(7)
    assert start == dispatcher.build_job_id(7) == "run:7:start"
    assert dispatcher.build_job_id(7, continue_run=True) == "run:7:continue"

    resume_a = dispatcher.build_job_id(7, resume_payload={"decision": "approved"})
    resume_b = dispatcher.build_job_id(7, resume_payload={"decision": "approved"})
    resume_c = dispatcher.build_job_id(7, resume_payload={"decision": "rejected"})
    assert resume_a == resume_b
    assert resume_a != resume_c
    # 不同 run 之间不互相串
    assert dispatcher.build_job_id(8) != start


def test_worker_settings_wired() -> None:
    from app.worker.main import WorkerSettings

    names = {
        getattr(fn, "name", None) or getattr(fn, "__name__", "")
        for fn in WorkerSettings.functions
    }
    assert {"run_pipeline", "resume_pipeline"} <= names
    assert WorkerSettings.queue_name == "devpipeline"
    assert WorkerSettings.health_check_key == "devpipeline:health"
    assert WorkerSettings.max_tries == 1
    assert WorkerSettings.job_timeout >= 600
    assert WorkerSettings.redis_settings is not None
