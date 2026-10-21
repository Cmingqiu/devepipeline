from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = pytest.mark.pg


async def test_readyz_checks_all_dependencies(project_factory):
    """M3 起 PG 与 Redis 都是必需依赖：三项都为 ok。"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/readyz")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"mariadb": "ok", "postgres": "ok", "redis": "ok"}
