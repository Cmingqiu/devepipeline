from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, SemanticError
from app.db.base import utcnow
from app.models import Project, Requirement, RequirementVersion
from app.schemas.requirement import RequirementCreate, VersionCreate

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 需求 .md 上限 2MB


async def _get_project_or_404(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    return project


async def list_requirements(
    session: AsyncSession,
    *,
    project_id: int,
    page: int,
    page_size: int,
    q: str | None = None,
) -> tuple[list[Requirement], int]:
    await _get_project_or_404(session, project_id)

    filters = [Requirement.project_id == project_id]
    if q:
        filters.append(Requirement.title.like(f"%{q.strip()}%"))

    total = (
        await session.execute(select(func.count()).select_from(Requirement).where(*filters))
    ).scalar_one()
    stmt = (
        select(Requirement)
        .where(*filters)
        .order_by(Requirement.updated_at.desc(), Requirement.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = list((await session.execute(stmt)).scalars().all())
    return items, int(total)


async def get_requirement(session: AsyncSession, requirement_id: int) -> Requirement:
    requirement = await session.get(Requirement, requirement_id)
    if requirement is None:
        raise NotFoundError("需求不存在")
    return requirement


async def get_version(
    session: AsyncSession, requirement_id: int, version_no: int
) -> RequirementVersion:
    stmt = (
        select(RequirementVersion)
        .where(
            RequirementVersion.requirement_id == requirement_id,
            RequirementVersion.version_no == version_no,
        )
        .limit(1)
    )
    version = (await session.execute(stmt)).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"需求版本 v{version_no} 不存在")
    return version


async def get_detail(
    session: AsyncSession, requirement_id: int
) -> tuple[Requirement, RequirementVersion]:
    requirement = await get_requirement(session, requirement_id)
    version = await get_version(session, requirement_id, requirement.current_version_no)
    return requirement, version


async def create_requirement(
    session: AsyncSession, project_id: int, payload: RequirementCreate
) -> tuple[Requirement, RequirementVersion]:
    project = await _get_project_or_404(session, project_id)
    requirement = Requirement(
        project_id=project.id,
        title=payload.title.strip(),
        current_version_no=1,
        status="draft",
    )
    session.add(requirement)
    await session.flush()  # 取到自增 id 后再写版本（不依赖 relationship）
    version = RequirementVersion(
        requirement_id=requirement.id,
        version_no=1,
        content=payload.content,
        source="editor",
        note=payload.note,
        created_by="local",
    )
    session.add(version)
    await session.commit()
    return requirement, version


async def update_requirement_title(
    session: AsyncSession, requirement_id: int, title: str
) -> Requirement:
    requirement = await get_requirement(session, requirement_id)
    requirement.title = title.strip()
    await session.commit()
    return requirement


async def delete_requirement(session: AsyncSession, requirement_id: int) -> None:
    requirement = await get_requirement(session, requirement_id)
    # 无外键，版本要显式删（先删子行再删主行）
    await session.execute(
        delete(RequirementVersion).where(RequirementVersion.requirement_id == requirement_id)
    )
    await session.delete(requirement)
    await session.commit()


async def list_versions(
    session: AsyncSession, requirement_id: int, *, page: int, page_size: int
) -> tuple[list[dict], int]:
    await get_requirement(session, requirement_id)
    # 只取元数据，不拉 LONGTEXT 正文
    columns = (
        RequirementVersion.id,
        RequirementVersion.version_no,
        RequirementVersion.source,
        RequirementVersion.note,
        RequirementVersion.created_by,
        RequirementVersion.created_at,
    )
    total = (
        await session.execute(
            select(func.count())
            .select_from(RequirementVersion)
            .where(RequirementVersion.requirement_id == requirement_id)
        )
    ).scalar_one()
    stmt = (
        select(*columns)
        .where(RequirementVersion.requirement_id == requirement_id)
        .order_by(RequirementVersion.version_no.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [dict(row) for row in rows], int(total)


async def _append_version(
    session: AsyncSession,
    requirement_id: int,
    *,
    content: str,
    source: str,
    note: str | None,
) -> RequirementVersion:
    # 行锁保证并发追加时版本号不撞唯一键
    stmt = select(Requirement).where(Requirement.id == requirement_id).with_for_update()
    requirement = (await session.execute(stmt)).scalar_one_or_none()
    if requirement is None:
        raise NotFoundError("需求不存在")

    new_no = requirement.current_version_no + 1
    version = RequirementVersion(
        requirement_id=requirement.id,
        version_no=new_no,
        content=content,
        source=source,
        note=note,
        created_by="local",
    )
    session.add(version)
    requirement.current_version_no = new_no
    requirement.updated_at = utcnow()
    await session.commit()
    return version


async def create_version(
    session: AsyncSession, requirement_id: int, payload: VersionCreate
) -> RequirementVersion:
    return await _append_version(
        session,
        requirement_id,
        content=payload.content,
        source="editor",
        note=payload.note,
    )


async def create_version_from_upload(
    session: AsyncSession,
    requirement_id: int,
    *,
    filename: str,
    raw: bytes,
    note: str | None,
) -> RequirementVersion:
    if not filename.lower().endswith(".md"):
        raise SemanticError("只接受 .md 文件")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise SemanticError(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SemanticError("文件必须是 UTF-8 编码的 Markdown") from exc
    if not content.strip():
        raise SemanticError("文件内容为空")

    return await _append_version(
        session,
        requirement_id,
        content=content,
        source="upload",
        note=note or filename,
    )
