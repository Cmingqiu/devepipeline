from __future__ import annotations

import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Project, Requirement
from app.schemas.project import ProjectCreate, ProjectUpdate

_SLUG_SEP = re.compile(r"[^a-z0-9]+")


def make_slug(name: str) -> str:
    """中文标题生成不出 slug —— 交给调用方兜底成随机短码。"""
    slug = _SLUG_SEP.sub("-", name.strip().lower())
    return re.sub(r"-{2,}", "-", slug).strip("-")[:64].strip("-")


async def _unique_slug(session: AsyncSession, base: str, exclude_id: int | None = None) -> str:
    root = base or f"p-{secrets.token_hex(4)}"
    candidate, n = root, 1
    while True:
        stmt = select(Project.id).where(Project.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.where(Project.id != exclude_id)
        if (await session.execute(stmt.limit(1))).first() is None:
            return candidate
        n += 1
        suffix = f"-{n}"
        candidate = f"{root[: 64 - len(suffix)]}{suffix}"


async def list_projects(
    session: AsyncSession, *, page: int, page_size: int, status: str | None = None
) -> tuple[list[tuple[Project, int]], int]:
    filters = [Project.status == status] if status else []
    total = (
        await session.execute(select(func.count()).select_from(Project).where(*filters))
    ).scalar_one()

    stmt = (
        select(Project, func.count(Requirement.id))
        .outerjoin(Requirement, Requirement.project_id == Project.id)
        .where(*filters)
        .group_by(Project.id)
        .order_by(Project.created_at.desc(), Project.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await session.execute(stmt)).all()
    return [(project, int(count)) for project, count in rows], int(total)


async def get_project(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    return project


async def requirement_count(session: AsyncSession, project_id: int) -> int:
    stmt = select(func.count()).select_from(Requirement).where(Requirement.project_id == project_id)
    return int((await session.execute(stmt)).scalar_one())


async def create_project(session: AsyncSession, payload: ProjectCreate) -> Project:
    if payload.slug:
        # 显式指定的 slug 冲突就是冲突，不自动加后缀（调用方要能感知 409）
        stmt = select(Project.id).where(Project.slug == payload.slug).limit(1)
        if (await session.execute(stmt)).first() is not None:
            raise ConflictError("slug 已被占用")
        slug = payload.slug
    else:
        # 自动生成的 slug（含中文标题兜底 p-xxxx）重复时加序号
        slug = await _unique_slug(session, make_slug(payload.name))

    project = Project(
        name=payload.name.strip(),
        slug=slug,
        description=payload.description,
        status="active",
    )
    session.add(project)
    try:
        await session.commit()
    except IntegrityError as exc:  # 并发下仍可能撞唯一键
        await session.rollback()
        raise ConflictError("slug 已被占用") from exc
    return project


async def update_project(session: AsyncSession, project_id: int, payload: ProjectUpdate) -> Project:
    project = await get_project(session, project_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        project.name = data["name"].strip()
    if "description" in data:
        project.description = data["description"]
    if "status" in data and data["status"] is not None:
        project.status = data["status"]
    await session.commit()
    return project


async def delete_project(session: AsyncSession, project_id: int) -> None:
    project = await get_project(session, project_id)
    if await requirement_count(session, project_id) > 0:
        raise ConflictError("项目下还有需求，不能删除（请先删除需求或归档项目）")
    await session.delete(project)
    await session.commit()
