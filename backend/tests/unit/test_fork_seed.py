from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.fork import (
    build_fork_seed,
    normalize_stage,
    route_gate_for,
    stage_from_snapshot,
)
from app.core.exceptions import SemanticError


def _values() -> dict:
    return {
        "run_id": 7,
        "analysis_doc": "A",
        "design_doc": "D",
        "code_diff": "C",
        "review_report": "R",
        "revisions": {"design": 1, "review": 2},
        "gate_decisions": {
            "analysis": {"decision": "approved"},
            "design": {"decision": "rejected"},
        },
        "review_round": 2,
        "max_review_rounds": 5,
        "focus_feedback": "旧意见",
        "error": "review_round_exceeded",
        "last_stage": {"stage": "review"},
        "pull_request_url": "https://github.com/acme/demo/pull/1",
        "pull_request_number": 1,
        "messages": [object()],
        "raw_requirement": "需求正文",
        "agents_md": "# AGENTS.md",
    }


def test_fork_seed_from_design_keeps_earlier_stage():
    seed = build_fork_seed(_values(), "design", run_id=99, max_review_rounds=3)

    assert seed["analysis_doc"] == "A"
    for field in ("design_doc", "code_diff", "review_report"):
        assert field not in seed
    assert seed["revisions"] == {}
    assert seed["gate_decisions"]["analysis"] == {"decision": "approved"}
    assert "design" not in seed["gate_decisions"]
    assert seed["review_round"] == 0
    assert seed["max_review_rounds"] == 3
    assert seed["focus_feedback"] == ""
    assert seed["last_stage"] == {}
    assert seed["run_id"] == 99
    assert seed["messages"] == []
    assert "error" not in seed
    assert "pull_request_url" not in seed
    # 父 run 的冻结上下文保留
    assert seed["raw_requirement"] == "需求正文"
    assert seed["agents_md"] == "# AGENTS.md"


def test_fork_seed_from_analysis_drops_everything_but_context():
    seed = build_fork_seed(_values(), "analysis", run_id=100, max_review_rounds=2)

    for field in ("analysis_doc", "design_doc", "code_diff", "review_report"):
        assert field not in seed
    assert seed["gate_decisions"] == {}
    assert seed["raw_requirement"] == "需求正文"


def test_fork_seed_does_not_mutate_source_values():
    values = _values()
    build_fork_seed(values, "coding", run_id=1, max_review_rounds=2)
    assert values["code_diff"] == "C"
    assert values["run_id"] == 7


def test_normalize_stage_rejects_unknown():
    with pytest.raises(SemanticError):
        normalize_stage("deploy")
    assert normalize_stage(None, "coding") == "coding"


def test_route_gate_mapping():
    assert route_gate_for("analysis") is None
    assert route_gate_for("design") == "gate_analysis"
    assert route_gate_for("coding") == "gate_design"
    assert route_gate_for("review") == "gate_coding"


def test_stage_from_snapshot_prefers_last_stage_then_next():
    snapshot = SimpleNamespace(values={"last_stage": {"stage": "coding"}}, next=("gate_coding",))
    assert stage_from_snapshot(snapshot) == "coding"

    snapshot = SimpleNamespace(values={}, next=("design_system",))
    assert stage_from_snapshot(snapshot) == "design"

    snapshot = SimpleNamespace(values={}, next=())
    assert stage_from_snapshot(snapshot) == "analysis"
