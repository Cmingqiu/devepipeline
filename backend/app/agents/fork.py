"""从 checkpoint 分叉：新 run 继承前序阶段产物，从 `from_stage` 的节点重新执行。

为什么不复用旧 thread：原 run 的事件/产物/审批记录必须保持原样；分叉用新 thread，
旧 checkpoint 只作为初值来源。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agents.state import STAGE_DOC_FIELD, STAGE_ORDER
from app.core.exceptions import SemanticError

# from_stage -> 用来“伪造前一个 gate 已完成”的节点名；analysis 是图入口，不需要
FORK_AS_NODE: dict[str, str | None] = {
    "analysis": None,
    "design": "gate_analysis",
    "coding": "gate_design",
    "review": "gate_coding",
}


def normalize_stage(from_stage: str | None, fallback: str | None = None) -> str:
    chosen = (from_stage or fallback or "analysis").strip()
    if chosen not in STAGE_ORDER:
        raise SemanticError(f"未知阶段：{chosen}")
    return chosen


def stage_from_snapshot(snapshot: Any, fallback: str = "analysis") -> str:
    """优先取 last_stage；没有就用 next 指向的节点（例如刚开始的 checkpoint）。"""
    values = getattr(snapshot, "values", None) or {}
    stage = str((values.get("last_stage") or {}).get("stage") or "")
    if stage in STAGE_ORDER:
        return stage
    from app.agents.graph import NODE_TO_STAGE

    for node in getattr(snapshot, "next", None) or ():
        mapped = NODE_TO_STAGE.get(str(node))
        if mapped:
            return mapped
    return fallback


def build_fork_seed(
    values: dict[str, Any],
    from_stage: str,
    *,
    run_id: int,
    max_review_rounds: int,
) -> dict[str, Any]:
    """清掉 `from_stage` 及之后的产物与决策，前面的阶段原样保留。"""
    from_stage = normalize_stage(from_stage)
    seed: dict[str, Any] = deepcopy(values or {})
    start = STAGE_ORDER.index(from_stage)
    dropped = set(STAGE_ORDER[start:])

    for stage in dropped:
        seed.pop(STAGE_DOC_FIELD[stage], None)
    seed["revisions"] = {
        key: value for key, value in (seed.get("revisions") or {}).items() if key not in dropped
    }
    decisions = {
        key: value
        for key, value in (seed.get("gate_decisions") or {}).items()
        if key not in dropped
    }
    # 前序阶段必须视为已通过，否则伪造 as_node 后条件边会把流程带回上一次驳回
    for stage in STAGE_ORDER[:start]:
        decisions[stage] = {"decision": "approved"}
    seed["gate_decisions"] = decisions

    # 新 run 自己的标识与运行参数，绝不能沿用父 run 的 run_id（工具/沙箱按它注册）
    seed["run_id"] = run_id
    seed["max_review_rounds"] = max_review_rounds
    seed["review_round"] = 0
    seed["focus_feedback"] = ""
    seed["last_stage"] = {}
    seed.pop("error", None)
    seed.pop("pull_request_url", None)
    seed.pop("pull_request_number", None)
    # 父 run 的工具对话不进新 run，避免模型看到无关历史
    seed["messages"] = []
    return seed


def route_gate_for(from_stage: str) -> str | None:
    return FORK_AS_NODE[normalize_stage(from_stage)]


__all__ = [
    "FORK_AS_NODE",
    "build_fork_seed",
    "normalize_stage",
    "route_gate_for",
    "stage_from_snapshot",
]
