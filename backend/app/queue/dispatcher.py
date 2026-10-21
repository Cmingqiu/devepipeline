"""入队入口：业务代码只调用这里的 `enqueue_run`。

`QUEUE_BACKEND=arq` 时交给 arq worker；未配置或 Redis 不可用时回退到进程内队列，
保证「只起后端也能把流水线跑通」，代价是重启丢任务（M2 的已知限制）。
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.queue import inline

logger = get_logger(__name__)


async def enqueue_run(
    run_id: int, *, resume_payload: dict[str, Any] | None = None, continue_run: bool = False
) -> str:
    if get_settings().queue_backend.lower() == "arq":
        try:
            from app.queue.arq import enqueue_run as arq_enqueue

            job_id = await arq_enqueue(
                run_id, resume_payload=resume_payload, continue_run=continue_run
            )
            logger.info("run_enqueued", extra={"run_id": run_id, "backend": "arq"})
            return f"arq:{job_id}"
        except Exception:
            logger.exception("arq_enqueue_failed_fallback_inline", extra={"run_id": run_id})

    from app.services.run_executor import execute_run

    if resume_payload is not None:
        inline.submit(
            execute_run(run_id, resume_payload=resume_payload), name=f"resume-{run_id}"
        )
    else:
        inline.submit(
            execute_run(run_id, continue_run=continue_run), name=f"run-{run_id}"
        )
    logger.info("run_enqueued", extra={"run_id": run_id, "backend": "inline"})
    return "inline"
