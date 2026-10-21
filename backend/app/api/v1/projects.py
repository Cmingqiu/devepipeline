from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.v1.deps import PaginationDep, SessionDep
from app.models import Project
from app.schemas.common import Page
from app.schemas.project import ProjectCreate, ProjectDetail, ProjectOut, ProjectUpdate
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_out(project: Project, count: int = 0) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.requirement_count = count
    return out


@router.get("", response_model=Page[ProjectOut], summary="项目列表")
async def list_projects(
    session: SessionDep,
    pag: PaginationDep,
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(active|archived)$", description="按状态过滤"
    ),
) -> Page[ProjectOut]:
    rows, total = await project_service.list_projects(
        session, page=pag.page, page_size=pag.page_size, status=status_filter
    )
    return Page[ProjectOut](
        items=[_to_out(project, count) for project, count in rows],
        total=total,
        page=pag.page,
        page_size=pag.page_size,
    )


@router.post(
    "",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建项目（slug 冲突返回 409）",
)
async def create_project(session: SessionDep, payload: ProjectCreate) -> ProjectOut:
    project = await project_service.create_project(session, payload)
    return _to_out(project, 0)


@router.get("/{project_id}", response_model=ProjectDetail, summary="项目详情")
async def get_project(session: SessionDep, project_id: int) -> ProjectDetail:
    project = await project_service.get_project(session, project_id)
    count = await project_service.requirement_count(session, project_id)
    return ProjectDetail(**_to_out(project, count).model_dump())


@router.patch("/{project_id}", response_model=ProjectOut, summary="更新项目")
async def update_project(
    session: SessionDep, project_id: int, payload: ProjectUpdate
) -> ProjectOut:
    project = await project_service.update_project(session, project_id, payload)
    count = await project_service.requirement_count(session, project_id)
    return _to_out(project, count)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除项目（下面还有需求时 409）",
)
async def delete_project(session: SessionDep, project_id: int) -> None:
    await project_service.delete_project(session, project_id)
