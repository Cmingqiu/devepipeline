from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.schemas.common import OkBody

logger = get_logger(__name__)
router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=OkBody, summary="存活探针（不查依赖）")
async def healthz() -> OkBody:
    return OkBody()


@router.get("/readyz", summary="就绪探针：MariaDB 必查，PG/Redis 在 M2/M3 接入")
async def readyz(response: Response) -> dict:
    checks = {"mariadb": "ok", "postgres": "skipped", "redis": "skipped"}
    try:
        async with get_session_factory()() as session:
            await session.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001  探针必须把任何连接错误降级成 503，不能冒泡成 500
        checks["mariadb"] = "failed"
        logger.warning("readyz_mariadb_failed", extra={"error": str(exc)[:200]})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "checks": checks}

    return {"status": "ok", "checks": checks}
