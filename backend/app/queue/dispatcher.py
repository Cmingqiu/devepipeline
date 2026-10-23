"""入队入口：业务代码只调用这里的 `enqueue_run`。

选择顺序：
1. `QUEUE_BACKEND=arq` 且有 worker 心跳 → 交给 arq（Redis 队列），同一个 job_id 只入队一次；
2. worker 不在（没有心跳）/ Redis 不可用 → 回退进程内队列，保证「只起后端也能跑」；
   代价是重启会丢任务（由启动时的 reconcile + 心跳判断兜底）。

为什么要有心跳判断：2026-10-23 实测「worker 没起时 run 永远停在排队中、页面无任何反馈」。
把「有没有消费者」做成显式判断，而不是把任务丢进空队列赌运气。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.queue import inline

logger = get_logger(__name__)


def build_job_id(
    run_id: int,
    *,
    resume_payload: dict[str, Any] | None = None,
    continue_run: bool = False,
    dedupe_key: str | None = None,
) -> str:
    """确定性 job id：重复投递（双击启动、api 重启 requeue、重复审批）会被 arq 拒绝。"""
    if dedupe_key:
        suffix = dedupe_key
    elif resume_payload is not None:
        digest = hashlib.sha1(
            json.dumps(resume_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:12]
        suffix = f"resume:{digest}"
    elif continue_run:
        suffix = "continue"
    else:
        suffix = "start"
    return f"run:{run_id}:{suffix}"


async def enqueue_run(
    run_id: int,
    *,
    resume_payload: dict[str, Any] | None = None,
    continue_run: bool = False,
    dedupe_key: str | None = None,
) -> str:
    job_id = build_job_id(
        run_id,
        resume_payload=resume_payload,
        continue_run=continue_run,
        dedupe_key=dedupe_key,
    )

    if get_settings().queue_backend.lower() == "arq":
        try:
            from app.queue.arq import enqueue_run as arq_enqueue
            from app.queue.arq import worker_healthy

            if not await worker_healthy():
                logger.warning(
                    "worker_absent_fallback_inline",
                    extra={"run_id": run_id, "hint": "启动 worker：python worker.py"},
                )
            else:
                accepted = await arq_enqueue(
                    run_id,
                    resume_payload=resume_payload,
                    continue_run=continue_run,
                    job_id=job_id,
                )
                if accepted is None:
                    logger.info(
                        "run_enqueue_duplicate_ignored",
                        extra={"run_id": run_id, "job_id": job_id},
                    )
                    return f"arq:duplicate:{job_id}"
                logger.info(
                    "run_enqueued", extra={"run_id": run_id, "backend": "arq", "job_id": job_id}
                )
                return f"arq:{accepted}"
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
