from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.run import ArtifactDetail, ArtifactOut, ArtifactPatch
from app.services import artifact_service, run_service

router = APIRouter(tags=["artifacts"])


@router.get(
    "/runs/{run_id}/artifacts",
    response_model=Page[ArtifactOut],
    summary="运行的产物列表（不含正文）",
)
async def list_artifacts(
    session: SessionDep, run_id: int, pag: PaginationDep
) -> Page[ArtifactOut]:
    # 先确认运行存在（顺带校正状态）
    await run_service.get_run(session, run_id, reconcile=False)
    items, total = await artifact_service.list_artifacts(
        session, run_id, page=pag.page, page_size=pag.page_size
    )
    return Page[ArtifactOut](
        items=[ArtifactOut.model_validate(item) for item in items],
        total=total,
        page=pag.page,
        page_size=pag.page_size,
    )


@router.get("/artifacts/{artifact_id}", response_model=ArtifactDetail, summary="单个产物正文")
async def get_artifact(session: SessionDep, artifact_id: int) -> ArtifactDetail:
    artifact = await artifact_service.get_artifact(session, artifact_id)
    return ArtifactDetail.model_validate(artifact)


@router.patch(
    "/artifacts/{artifact_id}",
    response_model=ArtifactDetail,
    summary="人工编辑产物（生成 version+1，保留历史）",
)
async def patch_artifact(
    session: SessionDep, artifact_id: int, payload: ArtifactPatch
) -> ArtifactDetail:
    artifact = await artifact_service.edit_artifact(session, artifact_id, payload.content)
    return ArtifactDetail.model_validate(artifact)


__all__ = ["router"]
