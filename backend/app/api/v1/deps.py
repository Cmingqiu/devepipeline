from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class Pagination:
    """page 从 1 起，page_size 上限 100（远程库 RTT 高，默认 20 够用）。"""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码，从 1 起"),
        page_size: int = Query(20, ge=1, le=100, description="每页条数，最大 100"),
    ) -> None:
        self.page = page
        self.page_size = page_size


PaginationDep = Annotated[Pagination, Depends(Pagination)]
