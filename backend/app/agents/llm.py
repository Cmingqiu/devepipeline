"""模型接入：OpenAI 兼容端点（默认 DeepSeek），一家配置走通所有阶段。"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.exceptions import SemanticError

CHAT_SUFFIX = "/chat/completions"


class ProviderNotConfigured(SemanticError):
    """缺少 key 等配置：启动 run 前置校验直接 422，不让运行到一半才炸。"""

    code = "provider_not_configured"


def to_base_url(endpoint: str) -> str:
    """配置里存的是完整 endpoint，ChatOpenAI 要的是 base_url。

    `https://api.deepseek.com/chat/completions` -> `https://api.deepseek.com`
    不剥后缀会拼成 `.../chat/completions/chat/completions` -> 404。
    """
    cleaned = endpoint.strip().rstrip("/")
    cleaned = cleaned.removesuffix(CHAT_SUFFIX)
    return cleaned.rstrip("/")


def assert_provider_ready() -> None:
    """启动 run 前调用；没有 key 直接报 422。"""
    if not get_settings().llm_key_deepseek.strip():
        raise ProviderNotConfigured(
            "未配置 LLM key：请在 backend/.env 填 LLM_KEY_DEEPSEEK 后重启后端"
        )


def get_chat_model(stage: str) -> Any:
    """按阶段取模型。M2 只认环境变量里的单一 provider；M4 接 model_bindings 表。"""
    assert_provider_ready()
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        base_url=to_base_url(settings.llm_endpoint),
        api_key=settings.llm_key_deepseek,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
        max_retries=2,
        # 流式是 M3 实时面板的前提：非流式时 LangGraph 的 messages 模式只会吐一个整块
        streaming=True,
        stream_usage=True,
        tags=[f"stage:{stage}"],
    )
