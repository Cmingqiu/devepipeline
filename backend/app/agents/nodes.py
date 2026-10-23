"""节点实现：4 个执行节点 + 4 个审批门。

设计约束：这里**不碰数据库**。节点只返回 state 增量与 `last_stage`（时间、用量、产物），
由执行器统一落 MariaDB —— 图纯函数化后，测试可以完全不连库地验证路由与产物。

编码节点例外：它从进程内注册表取执行器预先装好的工具（MCP / 技能读取），
并通过 `get_stream_writer()` 把 tool_started / tool_finished 实时推给 SSE。

评审节点例外：PR 创建需要落 `pull_requests` 表、推送远端分支，由 `pr_service`
处理（失败降级为无 PR 评审），节点本身仍只返回 state 增量。
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.types import interrupt

from app.agents import prompts
from app.agents.llm import get_chat_model
from app.agents.state import DECISIONS, PipelineState, StageOutcome
from app.core.logging import get_logger
from app.db.base import utcnow

logger = get_logger(__name__)

MAX_TOOL_ITERS = 6


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


def _chunk_text(chunk: Any) -> str:
    """流式 chunk 的正文：不做 strip，否则 token 之间的空格会丢。"""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


async def _call_model(model: Any, messages: list[Any]) -> tuple[str, dict[str, int]]:
    """优先流式（messages 模式才能吐出增量 token），没有 astream 的假模型退回 ainvoke。"""
    astream = getattr(model, "astream", None)
    if astream is None:
        response = await model.ainvoke(messages)
        return _text_of(response), _usage_of(response)

    parts: list[str] = []
    usage: dict[str, int] = {}
    async for chunk in astream(messages):
        parts.append(_chunk_text(chunk))
        chunk_usage = _usage_of(chunk)
        if chunk_usage.get("prompt_tokens") or chunk_usage.get("completion_tokens"):
            usage = chunk_usage
    return "".join(parts).strip(), usage


def _stream_writer():
    """图内可用；不在图里（单元测试直接调节点）时返回 None。"""
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:  # noqa: BLE001  非图执行上下文里没有 writer
        return None


def _emit(writer, event_type: str, payload: dict[str, Any], stage: str) -> None:
    if writer is None:
        return
    try:
        writer({"type": event_type, "stage": stage, "payload": payload})
    except Exception:  # noqa: BLE001, S110  事件发不出去不能打断编码
        pass


def _short_args(args: Any, limit: int = 800) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(args)
    return text[:limit]


def _tool_output_text(output: Any) -> str:
    """MCP 工具常返回 content blocks（[{'type':'text','text':'5'}]），拆成纯文本回灌模型。"""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return "\n".join(parts)
    return str(output)


async def _stream_message(model: Any, messages: list[Any]) -> tuple[Any, dict[str, int]]:
    """流式聚合一整轮回复（需要拿 tool_calls，所以不能只看文本）。"""
    astream = getattr(model, "astream", None)
    if astream is None:
        response = await model.ainvoke(messages)
        return response, _usage_of(response)

    aggregate = None
    usage: dict[str, int] = {}
    async for chunk in astream(messages):
        aggregate = chunk if aggregate is None else aggregate + chunk
        chunk_usage = _usage_of(chunk)
        if chunk_usage.get("prompt_tokens") or chunk_usage.get("completion_tokens"):
            usage = chunk_usage
    return aggregate, usage


async def _run_tool_loop(
    model: Any,
    tools: list[Any],
    messages: list[Any],
    *,
    stage: str,
) -> tuple[str, dict[str, int], int]:
    """工具调用循环：最多 MAX_TOOL_ITERS 轮；工具事件通过 stream writer 实时发出。"""
    writer = _stream_writer()
    by_name = {item.name: item for item in tools}
    bound = model.bind_tools(tools) if hasattr(model, "bind_tools") else model
    convo = list(messages)
    texts: list[str] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    tool_rounds = 0

    for _ in range(MAX_TOOL_ITERS):
        result, turn_usage = await _stream_message(bound, convo)
        usage["prompt_tokens"] += turn_usage.get("prompt_tokens", 0)
        usage["completion_tokens"] += turn_usage.get("completion_tokens", 0)
        if result is None:
            break
        convo.append(result)
        text = _text_of(result)
        if text:
            texts.append(text)

        calls = getattr(result, "tool_calls", None) or []
        if not calls:
            break
        tool_rounds += 1
        for call in calls:
            name = str(call.get("name") or "")
            args = call.get("args") or {}
            started = time.monotonic()
            _emit(writer, "tool_started", {"name": name, "args": _short_args(args)}, stage)
            tool = by_name.get(name)
            if tool is None:
                output, ok = f"未知工具：{name}", False
            else:
                try:
                    output = await tool.ainvoke(args)
                    ok = True
                except Exception as exc:  # noqa: BLE001  工具失败要回灌给模型，不能中断整条流水线
                    output, ok = f"{type(exc).__name__}: {exc}", False
            duration = int((time.monotonic() - started) * 1000)
            normalized = _tool_output_text(output)
            _emit(
                writer,
                "tool_finished",
                {
                    "name": name,
                    "ok": ok,
                    "result": normalized[:2000],
                    "duration_ms": duration,
                },
                stage,
            )
            convo.append(
                ToolMessage(
                    content=normalized[:8000],
                    tool_call_id=str(call.get("id") or name),
                    name=name or None,
                )
            )
    return "\n\n".join(texts).strip(), usage, tool_rounds


def _attempt(state: PipelineState, stage: str) -> int:
    return int((state.get("revisions") or {}).get(stage, 0)) + 1


async def _run_stage(
    state: PipelineState,
    *,
    stage: str,
    prompt_builder,
    doc_field: str,
    kind: str,
    tools: list[Any] | None = None,
) -> dict[str, Any]:
    from app.agents.model_registry import get_run_model
    from app.core.config import get_settings

    started = _now_iso()
    bindings = state.get("model_bindings") or {}
    binding = bindings.get(stage) or {}
    settings = get_settings()
    model = get_run_model(state.get("run_id"), stage) or get_chat_model(stage)
    system, user = prompt_builder(state)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    tool_rounds = 0
    if tools:
        text, usage, tool_rounds = await _run_tool_loop(model, tools, messages, stage=stage)
    else:
        text, usage = await _call_model(model, messages)
    finished = _now_iso()

    outcome: StageOutcome = {
        "stage": stage,
        "attempt": _attempt(state, stage),
        "started_at": started,
        "finished_at": finished,
        "usage": usage,
        "provider": str(binding.get("provider") or settings.llm_provider_name),
        "model": str(binding.get("model") or settings.llm_model),
        "tool_rounds": tool_rounds,
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
    from app.agents.tool_registry import get_run_sandbox, get_run_tools

    sandbox = get_run_sandbox(state.get("run_id"))
    result = await _run_stage(
        state,
        stage="coding",
        prompt_builder=prompts.coding_sandbox_prompt if sandbox is not None else prompts.coding_prompt,
        doc_field="code_diff",
        kind="diff",
        tools=get_run_tools(state.get("run_id")),
    )

    if sandbox is not None:
        # 沙箱里真实改过文件：产物 = 模型说明 + git diff + 命令/测试记录
        diff = await sandbox.diff()
        log = sandbox.command_log_summary()
        content = f"{result.get('code_diff') or ''}\n\n## 代码改动（git diff）\n{diff}"
        if log:
            content += f"\n\n## 命令与测试记录\n{log}"
        result["code_diff"] = content
        last_stage = dict(result.get("last_stage") or {})
        artifact = dict(last_stage.get("artifact") or {})
        artifact["content"] = content
        artifact["summary"] = _summary(content)
        last_stage["artifact"] = artifact
        result["last_stage"] = last_stage
    return result


async def pr_review(state: PipelineState) -> dict[str, Any]:
    pr_updates = await _ensure_pull_request(state)
    result = await _run_stage(
        state,
        stage="review",
        prompt_builder=prompts.review_prompt,
        doc_field="review_report",
        kind="markdown",
    )
    result.update(pr_updates)
    return result


async def _ensure_pull_request(state: PipelineState) -> dict[str, Any]:
    """评审前把沙箱分支推上去并建 PR；失败只发事件，不阻断评审。"""
    from app.agents.tool_registry import get_run_sandbox
    from app.services.pr_service import ensure_pull_request
    from app.vcs import VcsError

    writer = _stream_writer()
    run_id = int(state.get("run_id") or 0)
    workspace = get_run_sandbox(run_id) if run_id else None
    try:
        outcome = await ensure_pull_request(run_id, workspace)
    except VcsError as exc:
        logger.warning("pr_unavailable", extra={"run_id": run_id, "error": str(exc)[:300]})
        _emit(writer, "error", {"code": "pr_unavailable", "message": str(exc)[:500]}, "review")
        return {}
    except Exception as exc:  # PR 失败不能拖垮评审
        logger.exception("pr_failed", extra={"run_id": run_id})
        _emit(
            writer,
            "error",
            {"code": "pr_unavailable", "message": f"{type(exc).__name__}: {exc}"[:500]},
            "review",
        )
        return {}

    if outcome is None:
        return {}

    info = outcome.info
    _emit(
        writer,
        "pull_request_created",
        {
            "provider": info.provider,
            "number": info.number,
            "url": info.url,
            "branch": info.branch,
            "base_branch": info.base_branch,
            "head_sha": info.head_sha,
        },
        "review",
    )
    return {"pull_request_url": info.url, "pull_request_number": info.number}


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
