"""arq worker 启动入口（Windows 必须用这个，不能用 `-m arq`）。

`python -m arq` 会自己建事件循环，psycopg（checkpointer）在 Windows 上会直接报
"cannot use the ProactorEventLoop"；这里先钉死 selector 再交给 arq。

用法：
    conda run -n devpipeline python worker.py

Linux / docker 里两种方式都行：`arq app.worker.main.WorkerSettings`。
"""

from __future__ import annotations

from app.core.server import configure_event_loop_policy
from app.worker.main import WorkerSettings


def main() -> None:
    configure_event_loop_policy()
    from arq.worker import run_worker

    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
