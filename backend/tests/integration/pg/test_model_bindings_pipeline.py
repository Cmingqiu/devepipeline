from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import delete, select

from app.db.session import get_session_factory
from app.models import Credential, LlmProvider, ModelBinding, PipelineRun, StageRun
from app.schemas.llm import BindingItem, ProviderIn
from app.schemas.run import RunCreate
from app.services import provider_service, run_service
from app.services.run_executor import execute_run, get_graph, graph_config

pytestmark = pytest.mark.pg


@pytest.fixture
async def provider_factory():
    created: list[int] = []

    async def _make(
        name: str = "pipe-provider",
        api_key: str | None = "sk-pipe",
        model: str = "m-pipe",
    ) -> dict:
        async with get_session_factory()() as session:
            out = await provider_service.create_provider(
                session,
                ProviderIn(name=name, endpoint="https://api.example.com", model=model, api_key=api_key),
            )
        created.append(int(out["id"]))
        return out

    yield _make

    async with get_session_factory()() as session:
        for provider_id in created:
            await session.execute(
                delete(ModelBinding).where(ModelBinding.provider_id == provider_id)
            )
            provider = await session.get(LlmProvider, provider_id)
            if provider is None:
                continue
            if provider.credential_id:
                credential = await session.get(Credential, provider.credential_id)
                if credential is not None:
                    await session.delete(credential)
            await session.delete(provider)
        await session.commit()


async def _bind(session, project_id: int, items: list[BindingItem]) -> None:
    await provider_service.upsert_bindings(
        session, scope="project", project_id=project_id, items=items
    )


class _FakeModel:
    def __init__(self, stage: str, sink: list | None = None) -> None:
        self.stage = stage
        self.sink = sink

    def bind_tools(self, tools):
        return self

    async def astream(self, messages):
        yield AIMessageChunk(
            content=f"# {self.stage} 产物\n",
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )


async def test_bound_provider_is_used_and_recorded(
    project_factory, provider_factory, real_model_bindings, monkeypatch
):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "sk-env", raising=False)

    provider = await provider_factory()
    project_id, requirement_id = await project_factory(name="绑定项目")
    async with get_session_factory()() as session:
        await _bind(session, project_id, [BindingItem(stage="analysis", provider_id=provider["id"])])

    used: list[tuple[str, str, str]] = []

    class _BoundModel:
        def __init__(self, config, api_key: str) -> None:
            self.config = config
            self.api_key = api_key

        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            used.append(
                (self.config["stage"], self.config["model"], self.api_key)
            )
            yield AIMessageChunk(
                content="# analysis 绑定模型产物\n",
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            )

    monkeypatch.setattr(
        "app.agents.llm.build_chat_model", lambda config, api_key: _BoundModel(config, api_key)
    )
    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _FakeModel(stage), raising=True
    )

    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
    await execute_run(run.id)  # analysis 门

    # 节点用的是绑定 provider 的模型，密钥从 credential 解密得到
    assert used == [("analysis", "m-pipe", "sk-pipe")]

    async with get_session_factory()() as session:
        stage_run = (
            await session.execute(
                select(StageRun).where(StageRun.run_id == run.id, StageRun.stage == "analysis")
            )
        ).scalar_one()
    assert stage_run.provider == "pipe-provider"
    assert stage_run.model == "m-pipe"

    # state 快照冻结了绑定，但不含密钥
    graph = await get_graph()
    async with get_session_factory()() as session:
        stored = await session.get(PipelineRun, run.id)
    snapshot = await graph.aget_state(graph_config(stored))
    bindings = snapshot.values["model_bindings"]
    assert bindings["analysis"]["provider"] == "pipe-provider"
    assert bindings["design"]["source"] == "env"
    assert "sk-pipe" not in json.dumps(bindings, ensure_ascii=False)


async def test_unconfigured_binding_blocks_create_run(
    project_factory, provider_factory, real_model_bindings, monkeypatch
):
    from app.agents.llm import ProviderNotConfigured
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "", raising=False)

    provider = await provider_factory(name="no-key-pipe-provider", api_key=None)
    project_id, requirement_id = await project_factory(name="无密钥绑定项目")
    async with get_session_factory()() as session:
        await _bind(session, project_id, [BindingItem(stage="analysis", provider_id=provider["id"])])

    async with get_session_factory()() as session:
        with pytest.raises(ProviderNotConfigured) as excinfo:
            await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
    assert "analysis" in str(excinfo.value)
