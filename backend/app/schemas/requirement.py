from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

RequirementStatus = Literal[
    "draft", "queued", "running", "waiting_approval", "done", "failed", "cancelled"
]
VersionSource = Literal["editor", "upload", "ai"]


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    note: str | None = Field(default=None, max_length=255)


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    status: str
    current_version_no: int
    latest_run_id: int | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class RequirementDetail(RequirementOut):
    # 当前版本正文与版本号（列表接口不带正文，避免拉 LONGTEXT）
    content: str
    version_no: int


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_no: int
    source: str
    note: str | None = None
    created_by: str | None = None
    created_at: UtcDatetime


class VersionDetail(VersionOut):
    content: str


class VersionCreate(BaseModel):
    content: str = Field(min_length=1)
    note: str | None = Field(default=None, max_length=255)
