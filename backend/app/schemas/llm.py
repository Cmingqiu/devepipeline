from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

StageLiteral = Literal["analysis", "design", "coding", "review"]
BindingScope = Literal["global", "project"]


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    endpoint: str = Field(min_length=4, max_length=512)
    model: str = Field(min_length=1, max_length=128)
    api_key: str | None = Field(default=None, max_length=512, description="留空则读环境变量 LLM_KEY_<NAME>")
    extra: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    endpoint: str | None = Field(default=None, min_length=4, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    api_key: str | None = Field(default=None, max_length=512, description="留空表示不修改")
    extra: dict[str, Any] | None = None
    enabled: bool | None = None


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    endpoint: str
    model: str
    enabled: bool
    credential_id: int | None = None
    configured: bool = False
    credential_hint: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class BindingItem(BaseModel):
    stage: StageLiteral
    provider_id: int | None = None
    model: str | None = Field(default=None, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)


class BindingsIn(BaseModel):
    scope: BindingScope = "project"
    project_id: int | None = Field(default=None, description="scope=project 时必填；global 可传用于返回生效视图")
    items: list[BindingItem] = Field(default_factory=list)


class BindingOut(BaseModel):
    stage: str
    provider_id: int | None = None
    provider_name: str | None = None
    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    source: BindingScope | Literal["env"]
    configured: bool = False
    # 项目层原始覆盖值（回填表单用）；没有项目绑定时为空，避免把 global/env 的生效值存成项目覆盖
    override_model: str | None = None
    override_params: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BindingItem",
    "BindingOut",
    "BindingsIn",
    "ProviderIn",
    "ProviderOut",
    "ProviderPatch",
    "StageLiteral",
]
