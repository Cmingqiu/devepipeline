from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, PlainSerializer

T = TypeVar("T")


def _serialize_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# DB 里存 UTC naive，出参统一成带 Z 的 ISO8601
UtcDatetime = Annotated[datetime, PlainSerializer(_serialize_utc, return_type=str)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    trace_id: str


class OkBody(BaseModel):
    status: str = "ok"
