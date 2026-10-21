"""`python -m app` 启动入口：先在 Windows 上钉死 selector 事件循环，再起 uvicorn。"""

from __future__ import annotations

import asyncio
import sys


def _select_event_loop_policy() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    _select_event_loop_policy()
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, log_level="info")


if __name__ == "__main__":
    main()
