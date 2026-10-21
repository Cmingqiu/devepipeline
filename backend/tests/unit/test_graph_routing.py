from __future__ import annotations

from typing import Any

from app.agents.graph import (
    EXEC_NODES,
    GATE_NODES,
    route_after_analysis,
    route_after_coding,
    route_after_design,
    route_after_review,
)


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "gate_decisions": {},
        "revisions": {},
        "review_round": 0,
        "max_review_rounds": 2,
    }
    base.update(overrides)
    return base


def _decided(stage: str, decision: str) -> dict[str, Any]:
    return {"gate_decisions": {stage: {"decision": decision}}}


def test_exec_and_gate_nodes_cover_all_stages() -> None:
    assert set(EXEC_NODES) == {"analysis", "design", "coding", "review"}
    assert set(GATE_NODES) == {"analysis", "design", "coding", "review"}


def test_approve_routes_forward() -> None:
    assert route_after_analysis(_state(**_decided("analysis", "approved"))) == "design_system"
    assert route_after_design(_state(**_decided("design", "approved"))) == "coding"
    assert route_after_coding(_state(**_decided("coding", "approved"))) == "pr_review"
    assert route_after_review(_state(**_decided("review", "approved"))) == "__end__"


def test_edit_approval_routes_forward() -> None:
    assert route_after_analysis(_state(**_decided("analysis", "approved_with_edit"))) == "design_system"


def test_reject_routes_back_to_same_stage() -> None:
    assert route_after_analysis(_state(**_decided("analysis", "rejected"))) == "analyze_requirement"
    assert route_after_design(_state(**_decided("design", "rejected"))) == "design_system"
    assert route_after_coding(_state(**_decided("coding", "rejected"))) == "coding"


def test_review_reject_returns_to_coding_within_limit() -> None:
    state = _state(**_decided("review", "rejected"), review_round=1, max_review_rounds=2)
    assert route_after_review(state) == "coding"
    state = _state(**_decided("review", "rejected"), review_round=2, max_review_rounds=2)
    assert route_after_review(state) == "coding"


def test_review_reject_exceeding_limit_ends() -> None:
    state = _state(
        **_decided("review", "rejected"),
        review_round=3,
        max_review_rounds=2,
        error="review_round_exceeded",
    )
    assert route_after_review(state) == "__end__"


def test_abort_ends_every_gate() -> None:
    for router in (route_after_analysis, route_after_design, route_after_coding, route_after_review):
        stage = {
            route_after_analysis: "analysis",
            route_after_design: "design",
            route_after_coding: "coding",
            route_after_review: "review",
        }[router]
        assert router(_state(**_decided(stage, "aborted"))) == "__end__"
