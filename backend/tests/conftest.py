from __future__ import annotations

import asyncio
import sys

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import get_session
from app.main import create_app

# Windows：psycopg（M2 的 checkpointer）与统一选择都用 selector，测试环境先钉死
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
async def _close_global_resources():
    """pytest-asyncio 每个用例一个新事件循环；全局连接池必须跟着关，否则下个用例复用会报
    'Event loop is closed' / 'attached to a different loop'。"""
    yield
    from app.services import run_executor

    try:
        from app.db.graph_db import close_checkpointer

        await close_checkpointer()
    except Exception:  # noqa: BLE001, S110  清理是尽力而为，失败不影响用例结论
        pass
    run_executor.reset_graph()
    try:
        from app.db.session import dispose_engine

        await dispose_engine()
    except Exception:  # noqa: BLE001, S110  同上
        pass


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
async def engine(settings):
    eng = create_async_engine(settings.mariadb_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    """每个用例一个外层事务，结束回滚。

    Session 用 create_savepoint 加入外层事务，被测代码里的 commit() 只释放 savepoint，
    外层 rollback 后数据库回到测试前状态 —— 不需要清表，也不会污染真实数据。
    """
    async with engine.connect() as connection:
        trans = await connection.begin()
        test_session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield test_session
        finally:
            await test_session.close()
            await trans.rollback()


@pytest.fixture
async def client(session):
    app = create_app()

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
    app.dependency_overrides.clear()
