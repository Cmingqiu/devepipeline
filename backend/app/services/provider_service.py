"""LLM 提供商与每阶段模型绑定：CRUD + 解析顺序 + 密钥来源。

解析顺序（与 docs/architecture.md §4.3 一致）：
`model_bindings(project)` → `model_bindings(global)` → 环境变量默认 provider。
密钥不进 state/checkpoint：只保存 `credential_id`/provider name，运行时再解密或读环境变量。
"""

from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, SemanticError
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.models import Credential, LlmProvider, ModelBinding, Project
from app.schemas.llm import BindingItem, BindingOut, ProviderIn, ProviderPatch

logger = get_logger(__name__)

CHAT_SUFFIX = "/chat/completions"
STAGES: tuple[str, ...] = ("analysis", "design", "coding", "review")
GLOBAL_PROJECT_ID = 0


def normalize_endpoint(endpoint: str) -> str:
    """接口允许粘 base_url 或完整地址；统一存完整 chat completions 地址。"""
    text = (endpoint or "").strip().rstrip("/")
    if not text:
        raise SemanticError("endpoint 不能为空")
    if not text.endswith(CHAT_SUFFIX):
        text = f"{text}{CHAT_SUFFIX}"
    return text


def env_key_name(provider_name: str) -> str:
    return f"LLM_KEY_{provider_name.upper().replace('-', '_').replace('.', '_')}"


def env_key_value(provider_name: str) -> str:
    return os.environ.get(env_key_name(provider_name), "").strip()


def _parse_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _dump_json(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


async def _credential(session: AsyncSession, row: LlmProvider) -> Credential | None:
    if not row.credential_id:
        return None
    return await session.get(Credential, row.credential_id)


async def provider_secret(session: AsyncSession, row: LlmProvider) -> str | None:
    """密钥来源：credentials（Fernet 密文）→ 环境变量 LLM_KEY_<NAME>。"""
    credential = await _credential(session, row)
    if credential is not None:
        return decrypt_secret(credential.encrypted_blob, credential.key_version)
    return env_key_value(row.name) or None


async def provider_out(session: AsyncSession, row: LlmProvider) -> dict[str, Any]:
    credential = await _credential(session, row)
    secret = await provider_secret(session, row)
    return {
        "id": row.id,
        "name": row.name,
        "endpoint": row.endpoint,
        "model": row.model,
        "enabled": row.enabled,
        "credential_id": row.credential_id,
        "configured": secret is not None,
        "credential_hint": credential.hint if credential is not None else None,
        "extra": _parse_json(row.extra_json),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_providers(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (await session.execute(select(LlmProvider).order_by(LlmProvider.name))).scalars().all()
    )
    return [await provider_out(session, row) for row in rows]


async def _ensure_name_free(
    session: AsyncSession, name: str, *, exclude_id: int | None = None
) -> None:
    stmt = select(LlmProvider.id).where(LlmProvider.name == name)
    if exclude_id is not None:
        stmt = stmt.where(LlmProvider.id != exclude_id)
    if (await session.execute(stmt)).scalar_one_or_none() is not None:
        raise ConflictError(f"provider 名称已存在：{name}")


async def _store_secret(session: AsyncSession, row: LlmProvider, api_key: str) -> None:
    api_key = api_key.strip()
    if not api_key:
        return
    blob, version = encrypt_secret(api_key)
    credential = await _credential(session, row)
    if credential is None:
        credential = Credential(project_id=GLOBAL_PROJECT_ID, name=f"llm:{row.name}", kind="llm_key")
        session.add(credential)
    credential.encrypted_blob = blob
    credential.key_version = version
    credential.hint = mask_secret(api_key)
    await session.flush()
    row.credential_id = credential.id


async def create_provider(session: AsyncSession, payload: ProviderIn) -> dict[str, Any]:
    name = payload.name.strip()
    await _ensure_name_free(session, name)
    row = LlmProvider(
        name=name,
        endpoint=normalize_endpoint(payload.endpoint),
        model=payload.model.strip(),
        extra_json=_dump_json(payload.extra),
        enabled=payload.enabled,
    )
    session.add(row)
    await session.flush()
    await _store_secret(session, row, payload.api_key or "")
    await session.commit()
    return await provider_out(session, row)


async def update_provider(
    session: AsyncSession, provider_id: int, payload: ProviderPatch
) -> dict[str, Any]:
    row = await session.get(LlmProvider, provider_id)
    if row is None:
        raise NotFoundError("provider 不存在")
    if payload.name is not None:
        name = payload.name.strip()
        if name != row.name:
            await _ensure_name_free(session, name, exclude_id=row.id)
            row.name = name
    if payload.endpoint is not None:
        row.endpoint = normalize_endpoint(payload.endpoint)
    if payload.model is not None:
        row.model = payload.model.strip()
    if payload.extra is not None:
        row.extra_json = _dump_json(payload.extra)
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.api_key is not None:
        await _store_secret(session, row, payload.api_key)
    await session.commit()
    return await provider_out(session, row)


async def delete_provider(session: AsyncSession, provider_id: int) -> None:
    row = await session.get(LlmProvider, provider_id)
    if row is None:
        raise NotFoundError("provider 不存在")
    used = (
        await session.execute(
            select(ModelBinding.id).where(ModelBinding.provider_id == provider_id).limit(1)
        )
    ).scalar_one_or_none()
    if used is not None:
        raise ConflictError("该 provider 仍被阶段绑定引用，先解绑再删除")
    credential = await _credential(session, row)
    if credential is not None:
        await session.delete(credential)
    await session.delete(row)
    await session.commit()


# ---------------------------------------------------------------- 解析
async def _binding(
    session: AsyncSession, scope: str, project_id: int, stage: str
) -> ModelBinding | None:
    return (
        await session.execute(
            select(ModelBinding).where(
                ModelBinding.scope == scope,
                ModelBinding.project_id == project_id,
                ModelBinding.stage == stage,
            )
        )
    ).scalar_one_or_none()


async def resolve_stage_config(
    session: AsyncSession, project_id: int, stage: str
) -> dict[str, Any]:
    """返回该阶段最终生效配置（**不含密钥**，可以进 state/checkpoint）。"""
    binding = await _binding(session, "project", project_id, stage)
    if binding is None:
        binding = await _binding(session, "global", GLOBAL_PROJECT_ID, stage)

    if binding is not None:
        provider = await session.get(LlmProvider, binding.provider_id)
        if provider is not None and provider.enabled:
            params = {
                **_parse_json(provider.extra_json),
                **_parse_json(binding.params_json),
            }
            return {
                "stage": stage,
                "source": binding.scope,
                "provider_id": provider.id,
                "provider": provider.name,
                "endpoint": provider.endpoint,
                "model": (binding.model or provider.model).strip(),
                "params": params,
                "credential_id": provider.credential_id,
                "configured": (await provider_secret(session, provider)) is not None,
            }

    settings = get_settings()
    return {
        "stage": stage,
        "source": "env",
        "provider_id": None,
        "provider": settings.llm_provider_name,
        "endpoint": settings.llm_endpoint,
        "model": settings.llm_model,
        "params": {"temperature": settings.llm_temperature},
        "credential_id": None,
        "configured": bool(settings.llm_key_deepseek.strip()),
    }


async def resolve_project_bindings(
    session: AsyncSession, project_id: int
) -> dict[str, dict[str, Any]]:
    return {
        stage: await resolve_stage_config(session, project_id, stage) for stage in STAGES
    }


async def stage_secret(session: AsyncSession, config: dict[str, Any]) -> str | None:
    """运行时取密钥：绑定 provider 的 credential → 该 provider 的环境变量 → 默认 env key。"""
    if config.get("provider_id") is not None:
        provider = await session.get(LlmProvider, int(config["provider_id"]))
        if provider is not None:
            return await provider_secret(session, provider)
        return None
    return get_settings().llm_key_deepseek.strip() or None


async def assert_bindings_ready(session: AsyncSession, project_id: int) -> None:
    """启动 run 前校验每阶段都能拿到 key，避免跑一半才炸。"""
    from app.agents.llm import ProviderNotConfigured

    missing: list[str] = []
    for stage in STAGES:
        config = await resolve_stage_config(session, project_id, stage)
        if await stage_secret(session, config) is None:
            missing.append(stage)
    if missing:
        raise ProviderNotConfigured(
            f"阶段 {', '.join(missing)} 未配置 LLM 密钥：在「模型」里给 provider 填 api_key，"
            "或设置环境变量 LLM_KEY_<NAME>"
        )


# ---------------------------------------------------------------- 绑定
async def upsert_bindings(
    session: AsyncSession,
    *,
    scope: str,
    project_id: int | None,
    items: list[BindingItem],
) -> int:
    if scope == "project":
        if not project_id:
            raise SemanticError("scope=project 时必须传 project_id")
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFoundError("项目不存在")
    else:
        project_id = GLOBAL_PROJECT_ID

    seen: set[str] = set()
    for item in items:
        if item.stage in seen:
            raise SemanticError(f"阶段重复：{item.stage}")
        seen.add(item.stage)
        if item.provider_id is None:
            continue
        provider = await session.get(LlmProvider, item.provider_id)
        if provider is None:
            raise NotFoundError(f"provider 不存在：{item.provider_id}")
        if not provider.enabled:
            raise SemanticError(f"provider 已禁用：{provider.name}")

    await session.execute(
        delete(ModelBinding).where(
            ModelBinding.scope == scope, ModelBinding.project_id == int(project_id or 0)
        )
    )
    for item in items:
        if item.provider_id is None:
            continue
        session.add(
            ModelBinding(
                scope=scope,
                project_id=int(project_id or 0),
                stage=item.stage,
                provider_id=item.provider_id,
                model=(item.model or "").strip() or None,
                params_json=_dump_json(item.params),
            )
        )
    await session.commit()
    return len([item for item in items if item.provider_id is not None])


async def binding_view(session: AsyncSession, project_id: int) -> list[BindingOut]:
    out: list[BindingOut] = []
    for stage in STAGES:
        config = await resolve_stage_config(session, project_id, stage)
        project_binding = await _binding(session, "project", project_id, stage)
        out.append(
            BindingOut(
                stage=stage,
                provider_id=config["provider_id"],
                provider_name=config["provider"],
                model=config["model"],
                params=config["params"],
                source=config["source"],
                configured=config["configured"],
                override_model=project_binding.model if project_binding is not None else None,
                override_params=_parse_json(project_binding.params_json)
                if project_binding is not None
                else {},
            )
        )
    return out


__all__ = [
    "GLOBAL_PROJECT_ID",
    "STAGES",
    "assert_bindings_ready",
    "binding_view",
    "create_provider",
    "delete_provider",
    "env_key_name",
    "env_key_value",
    "list_providers",
    "normalize_endpoint",
    "provider_out",
    "provider_secret",
    "resolve_project_bindings",
    "resolve_stage_config",
    "stage_secret",
    "update_provider",
    "upsert_bindings",
]
