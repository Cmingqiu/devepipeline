"""节点实现：4 个执行节点 + 4 个审批门。

设计约束：这里**不碰数据库**。节点只返回 state 增量与 `last_stage`（时间、用量、产物），
由执行器统一落 MariaDB —— 图纯函数化后，测试可以完全不连库地验证路由与产物。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from app.agents import prompts
from app.agents.llm import get_chat_model
from app.agents.state import DECISIONS, PipelineState, StageOutcome
from app.db.base import utcnow


def _now_iso() -> str:
    return utcnow().isoformat(timespec="milliseconds") + "Z"


def _text_of(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                parts.append(str(block.get("text", "")))
        return "".join(parts).strip()
    return str(content).strip()


def _usage_of(message: Any) -> dict[str, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    return {
        "prompt_tokens": int(usage.get("input_tokens") or 0),
        "completion_tokens": int(usage.get("output_tokens") or 0),
    }


def _summary(text: str, limit: int = 300) -> str:
    return " ".join((text or "").split())[:limit]


def _attempt(state: PipelineState, stage: str) -> int:
    return int((state.get("revisions") or {}).get(stage, 0)) + 1


async def _run_stage(
    state: PipelineState,
    *,
    stage: str,
    prompt_builder,
    doc_field: str,
    kind: str,
) -> dict[str, Any]:
    started = _now_iso()
    model = get_chat_model(stage)
    system, user = prompt_builder(state)
    response = await model.ainvoke(
        [SystemMessage(content=system), HumanMessage(content=user)]
    )
    text = _text_of(response)
    finished = _now_iso()

    outcome: StageOutcome = {
        "stage": stage,
        "attempt": _attempt(state, stage),
        "started_at": started,
        "finished_at": finished,
        "usage": _usage_of(response),
        "artifact": {
            "kind": kind,
            "content": text,
            "summary": _summary(text),
            "edited_by_human": False,
        },
    }
    # focus_feedback 只对本次重跑生效，消费后清空
    return {doc_field: text, "focus_feedback": "", "last_stage": outcome}


async def analyze_requirement(state: PipelineState) -> dict[str, Any]:
    return await _run_stage(
        state,
        stage="analysis",
        prompt_builder=prompts.analysis_prompt,
        doc_field="analysis_doc",
        kind="markdown",
    )


async def design_system(state: PipelineState) -> dict[str, Any]:
    return await _run_stage(
        state,
        stage="design",
        prompt_builder=prompts.design_prompt,
        doc_field="design_doc",
        kind="markdown",
    )


async def coding(state: PipelineState) -> dict[str, Any]:
    return await _run_stage(
        state,
        stage="coding",
        prompt_builder=prompts.coding_prompt,
        doc_field="code_diff",
        kind="diff",
    )


async def pr_review(state: PipelineState) -> dict[str, Any]:
    return await _run_stage(
        state,
        stage="review",
        prompt_builder=prompts.review_prompt,
        doc_field="review_report",
        kind="markdown",
    )


def _gate(state: PipelineState, stage: str, doc_field: str, label: str) -> dict[str, Any]:
    """阻断在 gate 上等人工；resume 时返回值就是决策 payload。"""
    pending = {
        "stage": stage,
        "label": label,
        "attempt": _attempt(state, stage),
        "summary": _summary(state.get(doc_field, "")),
        "preview": (state.get(doc_field) or "")[:2000],
    }
    decision = interrupt(pending)
    return _apply_decision(state, stage, doc_field, decision)


def _apply_decision(
    state: PipelineState, stage: str, doc_field: str, decision: Any
) -> dict[str, Any]:
    raw = decision if isinstance(decision, dict) else {}
    chosen = str(raw.get("decision") or "rejected")
    if chosen not in DECISIONS:
        chosen = "rejected"

    entry = {
        "decision": chosen,
        "feedback": raw.get("feedback"),
        "decided_at": _now_iso(),
    }
    updates: dict[str, Any] = {
        "gate_decisions": {**(state.get("gate_decisions") or {}), stage: entry}
    }

    edited = raw.get("edited_content")
    if chosen == "approved_with_edit" and edited:
        # 人工改过的正文既是新产物，也是下游节点的输入
        updates[doc_field] = str(edited)
        updates["last_stage"] = {
            "stage": stage,
            "attempt": _attempt(state, stage),
            "started_at": _now_iso(),
            "finished_at": _now_iso(),
            "usage": {},
            "artifact": {
                "kind": "markdown" if doc_field != "code_diff" else "diff",
                "content": str(edited),
                "summary": _summary(str(edited)),
                "edited_by_human": True,
            },
        }

    if chosen == "rejected":
        revisions = dict(state.get("revisions") or {})
        revisions[stage] = int(revisions.get(stage, 0)) + 1
        updates["revisions"] = revisions
        updates["focus_feedback"] = str(raw.get("feedback") or "")
        if stage == "review":
            new_round = int(state.get("review_round", 0)) + 1
            updates["review_round"] = new_round
            if new_round > int(state.get("max_review_rounds", 2)):
                # 超过最大回退轮次：终止并保留错误码，交人工处理
                updates["error"] = "review_round_exceeded"

    if chosen == "aborted":
        updates["error"] = "aborted_by_human"

    return updates


async def gate_analysis(state: PipelineState) -> dict[str, Any]:
    return _gate(state, "analysis", "analysis_doc", "需求细节分析")


async def gate_design(state: PipelineState) -> dict[str, Any]:
    return _gate(state, "design", "design_doc", "系统设计")


async def gate_coding(state: PipelineState) -> dict[str, Any]:
    return _gate(state, "coding", "code_diff", "编码")


async def gate_review(state: PipelineState) -> dict[str, Any]:
    return _gate(state, "review", "review_report", "PR 评审")


__all__ = [
    "analyze_requirement",
    "coding",
    "design_system",
    "gate_analysis",
    "gate_coding",
    "gate_design",
    "gate_review",
    "pr_review",
]
