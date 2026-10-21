from __future__ import annotations

from datetime import UTC

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.common import UtcDatetime
from app.services.project_service import make_slug


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("My First Project", "my-first-project"),
        ("  Order   Service  ", "order-service"),
        ("v2.0 API", "v2-0-api"),
        ("a" * 80, "a" * 64),
    ],
)
def test_make_slug_normalizes(name: str, expected: str) -> None:
    assert make_slug(name) == expected


def test_make_slug_returns_empty_for_chinese() -> None:
    # 纯中文标题转换不出 ascii slug，调用方用 p-<random> 兜底
    assert make_slug("需求管理平台") == ""


def test_utc_datetime_serializes_with_z() -> None:
    from datetime import datetime

    from pydantic import BaseModel

    class Body(BaseModel):
        at: UtcDatetime

    body = Body(at=datetime(2026, 10, 21, 8, 12, 33, 412000, tzinfo=UTC))
    assert body.model_dump()["at"] == "2026-10-21T08:12:33.412Z"

    naive = Body(at=datetime(2026, 10, 21, 8, 12, 33, 412000))
    assert naive.model_dump()["at"] == "2026-10-21T08:12:33.412Z"


def test_error_types_carry_status_and_code() -> None:
    assert NotFoundError("x").status_code == 404
    assert NotFoundError("x").code == "not_found"
    assert ConflictError("x").status_code == 409
    assert ConflictError("x").code == "conflict"
