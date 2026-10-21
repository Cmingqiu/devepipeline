from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.queue import dispatcher, inline


async def test_dispatcher_falls_back_to_inline_when_arq_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "queue_backend", "arq", raising=False)

    async def _boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.queue.arq.enqueue_run", _boom, raising=True)

    backend = await dispatcher.enqueue_run(999999)
    assert backend == "inline"
    await inline.join()


def test_worker_settings_wired() -> None:
    from app.worker.main import WorkerSettings

    names = {getattr(fn, "name", None) or getattr(fn, "__name__", "") for fn in WorkerSettings.functions}
    assert {"run_pipeline", "resume_pipeline"} <= names
    assert WorkerSettings.queue_name == "devpipeline"
    assert WorkerSettings.max_tries == 1
    assert WorkerSettings.job_timeout >= 600
    assert WorkerSettings.redis_settings is not None
