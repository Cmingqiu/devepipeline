from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.v1.deps import PaginationDep, SessionDep
from app.models import Requirement, RequirementVersion
from app.schemas.common import Page
from app.schemas.requirement import (
    RequirementCreate,
    RequirementDetail,
    RequirementOut,
    RequirementUpdate,
    VersionCreate,
    VersionDetail,
    VersionOut,
)
from app.services import requirement_service

router = APIRouter(tags=["requirements"])


def _detail(requirement: Requirement, version: RequirementVersion) -> RequirementDetail:
    return RequirementDetail(
        id=requirement.id,
        project_id=requirement.project_id,
        title=requirement.title,
        status=requirement.status,
        current_version_no=requirement.current_version_no,
        latest_run_id=requirement.latest_run_id,
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
        content=version.content,
        version_no=version.version_no,
    )


def _version_detail(version: RequirementVersion) -> VersionDetail:
    return VersionDetail(
        id=version.id,
        version_no=version.version_no,
        source=version.source,
        note=version.note,
        created_by=version.created_by,
        created_at=version.created_at,
        content=version.content,
    )


@router.get(
    "/projects/{project_id}/requirements",
    response_model=Page[RequirementOut],
    summary="项目下的需求列表",
)
async def list_requirements(
    session: SessionDep,
    project_id: int,
    pag: PaginationDep,
    q: str | None = Query(default=None, max_length=200, description="标题模糊搜索"),
) -> Page[RequirementOut]:
    items, total = await requirement_service.list_requirements(
        session, project_id=project_id, page=pag.page, page_size=pag.page_size, q=q
    )
    return Page[RequirementOut](
        items=[RequirementOut.model_validate(item) for item in items],
        total=total,
        page=pag.page,
        page_size=pag.page_size,
    )


@router.post(
    "/projects/{project_id}/requirements",
    response_model=RequirementDetail,
    status_code=status.HTTP_201_CREATED,
    summary="新建需求（同时生成版本 v1）",
)
async def create_requirement(
    session: SessionDep, project_id: int, payload: RequirementCreate
) -> RequirementDetail:
    requirement, version = await requirement_service.create_requirement(
        session, project_id, payload
    )
    return _detail(requirement, version)


@router.get("/requirements/{requirement_id}", response_model=RequirementDetail, summary="需求详情")
async def get_requirement(session: SessionDep, requirement_id: int) -> RequirementDetail:
    requirement, version = await requirement_service.get_detail(session, requirement_id)
    return _detail(requirement, version)


@router.patch("/requirements/{requirement_id}", response_model=RequirementOut, summary="改需求标题")
async def update_requirement(
    session: SessionDep, requirement_id: int, payload: RequirementUpdate
) -> RequirementOut:
    if payload.title is None:
        requirement = await requirement_service.get_requirement(session, requirement_id)
    else:
        requirement = await requirement_service.update_requirement_title(
            session, requirement_id, payload.title
        )
    return RequirementOut.model_validate(requirement)


@router.delete(
    "/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除需求（连同版本）",
)
async def delete_requirement(session: SessionDep, requirement_id: int) -> None:
    await requirement_service.delete_requirement(session, requirement_id)


@router.get(
    "/requirements/{requirement_id}/versions",
    response_model=Page[VersionOut],
    summary="版本列表（不含正文）",
)
async def list_versions(
    session: SessionDep, requirement_id: int, pag: PaginationDep
) -> Page[VersionOut]:
    rows, total = await requirement_service.list_versions(
        session, requirement_id, page=pag.page, page_size=pag.page_size
    )
    return Page[VersionOut](
        items=[VersionOut(**row) for row in rows],
        total=total,
        page=pag.page,
        page_size=pag.page_size,
    )


@router.post(
    "/requirements/{requirement_id}/versions",
    response_model=VersionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="保存为新版本（source=editor）",
)
async def create_version(
    session: SessionDep, requirement_id: int, payload: VersionCreate
) -> VersionDetail:
    version = await requirement_service.create_version(session, requirement_id, payload)
    return _version_detail(version)


@router.post(
    "/requirements/{requirement_id}/versions/upload",
    response_model=VersionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="上传 .md 生成新版本（source=upload，≤2MB，UTF-8）",
)
async def upload_version(
    session: SessionDep,
    requirement_id: int,
    file: UploadFile = File(..., description="Markdown 文件"),  # noqa: B008  FastAPI 依赖注入的标准写法
    note: str | None = Form(default=None, max_length=255),
) -> VersionDetail:
    # 多读 1 字节即可判断超限，避免把超大文件整个读进内存
    raw = await file.read(requirement_service.MAX_UPLOAD_BYTES + 1)
    version = await requirement_service.create_version_from_upload(
        session,
        requirement_id,
        filename=file.filename or "",
        raw=raw,
        note=note.strip() if note and note.strip() else None,
    )
    return _version_detail(version)


@router.get(
    "/requirements/{requirement_id}/versions/{version_no}",
    response_model=VersionDetail,
    summary="单个版本正文",
)
async def get_version(
    session: SessionDep, requirement_id: int, version_no: int
) -> VersionDetail:
    version = await requirement_service.get_version(session, requirement_id, version_no)
    return _version_detail(version)
