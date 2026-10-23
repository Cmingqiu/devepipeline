from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from app.api.v1.deps import SessionDep
from app.core.exceptions import NotFoundError
from app.models import Project
from app.schemas.llm import BindingOut, BindingsIn, ProviderIn, ProviderOut, ProviderPatch
from app.services import provider_service

router = APIRouter(tags=["providers"])


@router.get("/providers", response_model=list[ProviderOut], summary="LLM provider 列表（密钥只回 hint）")
async def list_providers(session: SessionDep) -> list[ProviderOut]:
    rows = await provider_service.list_providers(session)
    return [ProviderOut(**row) for row in rows]


@router.post(
    "/providers",
    response_model=ProviderOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增 provider（api_key 加密入库；不填则读环境变量 LLM_KEY_<NAME>）",
)
async def create_provider(session: SessionDep, payload: ProviderIn) -> ProviderOut:
    return ProviderOut(**await provider_service.create_provider(session, payload))


@router.patch(
    "/providers/{provider_id}",
    response_model=ProviderOut,
    summary="修改 provider（api_key 留空表示不修改）",
)
async def update_provider(
    session: SessionDep, provider_id: int, payload: ProviderPatch
) -> ProviderOut:
    return ProviderOut(**await provider_service.update_provider(session, provider_id, payload))


@router.delete(
    "/providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 provider（被阶段绑定引用时 409）",
)
async def delete_provider(session: SessionDep, provider_id: int) -> Response:
    await provider_service.delete_provider(session, provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _ensure_project(session, project_id: int) -> None:
    if await session.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")


@router.get(
    "/model-bindings",
    response_model=list[BindingOut],
    summary="项目每阶段生效模型（含来源 project/global/env）",
)
async def get_bindings(
    session: SessionDep,
    project_id: int = Query(ge=1),
) -> list[BindingOut]:
    await _ensure_project(session, project_id)
    return await provider_service.binding_view(session, project_id)


@router.put(
    "/model-bindings",
    response_model=list[BindingOut],
    summary="整体替换某 scope 的阶段绑定（未出现的阶段视为解绑）",
)
async def put_bindings(session: SessionDep, payload: BindingsIn) -> list[BindingOut]:
    if payload.project_id:
        await _ensure_project(session, payload.project_id)
    await provider_service.upsert_bindings(
        session,
        scope=payload.scope,
        project_id=payload.project_id,
        items=payload.items,
    )
    return await provider_service.binding_view(session, payload.project_id or 0)


__all__ = ["router"]
