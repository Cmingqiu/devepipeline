"""流水线状态定义。字段与 docs/architecture.md §3.1 对齐。"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

Stage = Literal["analysis", "design", "coding", "review"]
Decision = Literal["approved", "approved_with_edit", "rejected", "aborted"]

STAGE_ORDER: tuple[str, ...] = ("analysis", "design", "coding", "review")
STAGE_LABELS: dict[str, str] = {
    "analysis": "需求细节分析",
    "design": "系统设计",
    "coding": "编码",
    "review": "PR 评审",
}
# 每个阶段产物落在 state 的哪个字段
STAGE_DOC_FIELD: dict[str, str] = {
    "analysis": "analysis_doc",
    "design": "design_doc",
    "coding": "code_diff",
    "review": "review_report",
}
DECISIONS: frozenset[str] = frozenset({"approved", "approved_with_edit", "rejected", "aborted"})


class GateDecision(TypedDict, total=False):
    decision: str
    feedback: str | None
    decided_at: str


class StageOutcome(TypedDict, total=False):
    stage: str
    attempt: int
    started_at: str
    finished_at: str
    usage: dict[str, int]
    artifact: dict[str, Any]


class PipelineState(TypedDict, total=False):
    # 标识
    run_id: int
    project_id: int
    requirement_id: int
    requirement_version_id: int
    # 输入快照（一次 run 冻结）
    raw_requirement: str
    agents_md: str
    skill_index: list[dict[str, str]]
    # 各阶段产物
    analysis_doc: str
    design_doc: str
    code_diff: str
    review_report: str
    # 人工决策与计数
    gate_decisions: dict[str, GateDecision]
    revisions: dict[str, int]
    review_round: int
    max_review_rounds: int
    focus_feedback: str
    # 最近一次节点执行结果（执行器据此落 stage_runs / artifacts）
    last_stage: StageOutcome
    # 终端错误（驳回超轮次、人工中止等）
    error: str
    # 供 M5 的工具调用消息使用
    messages: Annotated[list[AnyMessage], add_messages]
