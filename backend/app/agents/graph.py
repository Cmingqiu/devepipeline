"""流水线图：4 个执行节点 + 4 个审批门，gate 内 interrupt 等人工决策。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    analyze_requirement,
    coding,
    design_system,
    gate_analysis,
    gate_coding,
    gate_design,
    gate_review,
    pr_review,
)
from app.agents.state import PipelineState

EXEC_NODES: dict[str, Any] = {
    "analysis": analyze_requirement,
    "design": design_system,
    "coding": coding,
    "review": pr_review,
}
GATE_NODES: dict[str, Any] = {
    "analysis": gate_analysis,
    "design": gate_design,
    "coding": gate_coding,
    "review": gate_review,
}

# 节点名 → 阶段枚举。SSE 的 stage 字段必须是 analysis/design/coding/review，
# 不能把 langgraph 的节点名（analyze_requirement 等）直接丢给前端。
NODE_TO_STAGE: dict[str, str] = {
    **{fn.__name__: stage for stage, fn in EXEC_NODES.items()},
    **{fn.__name__: stage for stage, fn in GATE_NODES.items()},
}


def _decision(state: PipelineState, stage: str) -> str:
    return str(((state.get("gate_decisions") or {}).get(stage) or {}).get("decision") or "")


def route_after_analysis(state: PipelineState) -> str:
    decision = _decision(state, "analysis")
    if decision == "aborted":
        return END
    return "analyze_requirement" if decision == "rejected" else "design_system"


def route_after_design(state: PipelineState) -> str:
    decision = _decision(state, "design")
    if decision == "aborted":
        return END
    return "design_system" if decision == "rejected" else "coding"


def route_after_coding(state: PipelineState) -> str:
    decision = _decision(state, "coding")
    if decision == "aborted":
        return END
    return "coding" if decision == "rejected" else "pr_review"


def route_after_review(state: PipelineState) -> str:
    if state.get("error") == "review_round_exceeded":
        return END
    decision = _decision(state, "review")
    if decision == "aborted":
        return END
    if decision == "rejected" and int(state.get("review_round", 0)) <= int(
        state.get("max_review_rounds", 2)
    ):
        # review_round 在 gate 里已经 +1；未超上限则回到编码继续修
        return "coding"
    return END


def build_graph(checkpointer: Any = None, store: Any = None):
    """checkpointer 传 None 时图不可恢复（仅用于不落检查点的单元测试）。"""
    graph = StateGraph(PipelineState)

    graph.add_node("analyze_requirement", analyze_requirement)
    graph.add_node("gate_analysis", gate_analysis)
    graph.add_node("design_system", design_system)
    graph.add_node("gate_design", gate_design)
    graph.add_node("coding", coding)
    graph.add_node("gate_coding", gate_coding)
    graph.add_node("pr_review", pr_review)
    graph.add_node("gate_review", gate_review)

    graph.add_edge(START, "analyze_requirement")
    graph.add_edge("analyze_requirement", "gate_analysis")
    graph.add_conditional_edges(
        "gate_analysis", route_after_analysis, ["analyze_requirement", "design_system", END]
    )
    graph.add_edge("design_system", "gate_design")
    graph.add_conditional_edges(
        "gate_design", route_after_design, ["design_system", "coding", END]
    )
    graph.add_edge("coding", "gate_coding")
    graph.add_conditional_edges("gate_coding", route_after_coding, ["coding", "pr_review", END])
    graph.add_edge("pr_review", "gate_review")
    graph.add_conditional_edges("gate_review", route_after_review, ["coding", END])

    return graph.compile(checkpointer=checkpointer, store=store)
