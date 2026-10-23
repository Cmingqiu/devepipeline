from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import UtcDatetime


class RunCreate(BaseModel):
    version_no: int | None = Field(default=None, ge=1, description="用哪个需求版本跑，默认当前版本")
    max_review_rounds: int = Field(default=2, ge=0, le=10, description="评审驳回后回退编码的最大轮次")


class PendingApproval(BaseModel):
    stage: str
    label: str
    attempt: int = 1
    summary: str = ""
    preview: str = ""
    artifact_id: int | None = None
    checkpoint_id: str | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    requirement_id: int
    requirement_version_id: int
    thread_id: str
    status: str
    current_stage: str | None = None
    review_round: int = 0
    max_review_rounds: int = 2
    error_code: str | None = None
    error_message: str | None = None
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    prompt_tokens: int = 0
    completion_tokens: int = 0


class RunDetail(RunOut):
    pending_approval: PendingApproval | None = None


class ApprovalIn(BaseModel):
    decision: Literal["approved", "approved_with_edit", "rejected", "aborted"]
    feedback: str | None = Field(default=None, max_length=8000)
    edited_content: str | None = Field(default=None, description="approved_with_edit 时的正文")

    @model_validator(mode="after")
    def _check(self) -> ApprovalIn:
        if self.decision == "approved_with_edit" and not (self.edited_content or "").strip():
            raise ValueError("approved_with_edit 必须带 edited_content")
        if self.decision == "rejected" and not (self.feedback or "").strip():
            raise ValueError("rejected 必须带 feedback（驳回意见）")
        return self


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    stage: str
    artifact_id: int | None = None
    decision: str
    feedback: str | None = None
    decided_by: str | None = None
    decided_at: UtcDatetime


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    stage: str
    version: int
    kind: str
    summary: str | None = None
    edited_by_human: bool = False
    created_at: UtcDatetime


class ArtifactDetail(ArtifactOut):
    content: str


class ArtifactPatch(BaseModel):
    content: str = Field(min_length=1)


class StateSummary(BaseModel):
    checkpoint_id: str | None = None
    stage: str | None = None
    next: list[str] = Field(default_factory=list)
    created_at: str | None = None
    has_interrupt: bool = False
    error: str | None = None


class EventOut(BaseModel):
    seq: int
    ts: UtcDatetime
    stage: str | None = None
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)

class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    attempt: int
    mode: str
    repo_url: str
    workspace_path: str
    branch: str
    base_sha: str | None = None
    head_sha: str | None = None
    created_at: UtcDatetime
    cleaned_at: UtcDatetime | None = None
