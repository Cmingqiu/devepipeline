"""当前 run 的每阶段模型句柄（进程内注册表）。

为什么不放进 state/checkpoint：模型对象带 HTTP 客户端与 api_key，不可序列化，
也不该把密钥写进 PostgreSQL 的 checkpoint 表。执行器每次执行/恢复前按绑定的
provider 构造并注册，节点按 run_id 取；`finally` 清理。
"""

from __future__ import annotations

from typing import Any

_MODELS: dict[int, dict[str, Any]] = {}


def set_run_models(run_id: int, models: dict[str, Any]) -> None:
    if models:
        _MODELS[run_id] = models


def get_run_model(run_id: int | None, stage: str) -> Any:
    if run_id is None:
        return None
    return (_MODELS.get(int(run_id)) or {}).get(stage)


def clear_run_models(run_id: int) -> None:
    _MODELS.pop(run_id, None)


__all__ = ["clear_run_models", "get_run_model", "set_run_models"]
