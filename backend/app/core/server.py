"""uvicorn 启动器：`python main.py` 与 `python -m app` 共用这一份实现。

为什么单独抽出来：
- Windows 必须在**建事件循环之前**把策略钉成 selector（M2 的 psycopg 不支持 Proactor），
  入口文件越早设置越可靠；
- host/port/reload 从命令行或环境变量取，避免入口文件里散落硬编码。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

APP_IMPORT_STRING = "app.main:app"
APP_DIR = Path(__file__).resolve().parents[1]  # backend/app
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
LOG_LEVELS = ("critical", "error", "warning", "info", "debug", "trace")


def configure_event_loop_policy() -> None:
    """Windows 只支持 selector 跑 psycopg；Proactor 会在 checkpointer 初始化时直接报错。"""
    if sys.platform == "win32":
        if not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="启动 DevPipeline API（uvicorn）。参数优先级：命令行 > 环境变量 > 默认值",
    )
    parser.add_argument("--host", default=os.getenv("API_HOST", DEFAULT_HOST), help="监听地址")
    parser.add_argument(
        "--port", type=int, default=_env_int("API_PORT", DEFAULT_PORT), help="监听端口"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=_env_flag("API_RELOAD"),
        help="开发热重载（只监听 backend/app 目录）",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("API_LOG_LEVEL", "info").strip().lower(),
        choices=LOG_LEVELS,
        help="uvicorn 日志级别",
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    # 必须在 uvicorn 建 loop 之前
    configure_event_loop_policy()

    import uvicorn

    uvicorn.run(
        APP_IMPORT_STRING,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(APP_DIR)] if args.reload else None,
        # 明示用 asyncio：不让 uvicorn 走 uvloop / Proactor 分支
        loop="asyncio",
        log_level=args.log_level,
    )
