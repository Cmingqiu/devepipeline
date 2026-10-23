"""模型接入：OpenAI 兼容端点（默认 DeepSeek），一家配置走通所有阶段。

M4 起支持每阶段绑定不同 provider：`get_run_model(run_id, stage)` 优先，
没有绑定/未注册时回退到环境变量里的单一 provider。
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.exceptions import SemanticError
from app.services.provider_service import CHAT_SUFFIX

__all__ = [
    "CHAT_SUFFIX",
    "ProviderNotConfigured",
    "assert_provider_ready",
    "build_chat_model",
    "get_chat_model",
    "to_base_url",
]


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
    """兜底校验：没有环境变量 key 且没有绑定 provider 时，启动 run 直接 422。"""
    if not get_settings().llm_key_deepseek.strip():
        raise ProviderNotConfigured(
            "未配置 LLM key：请在「模型」里给 provider 填 api_key，或在 backend/.env 填 LLM_KEY_DEEPSEEK 后重启后端"
        )


def build_chat_model(config: dict[str, Any], api_key: str) -> Any:
    """按解析结果构造模型；config 不含密钥，密钥由调用方从 credential/env 取出。"""
    if not api_key:
        raise ProviderNotConfigured(f"provider {config.get('provider') or ''} 未配置 API key")
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    params = config.get("params") or {}
    kwargs: dict[str, Any] = {
        "base_url": to_base_url(str(config["endpoint"])),
        "api_key": api_key,
        "model": str(config["model"]),
        "temperature": float(params.get("temperature", settings.llm_temperature)),
        "timeout": float(params.get("timeout", settings.llm_timeout)),
        "max_retries": 2,
        # 流式是 M3 实时面板的前提：非流式时 LangGraph 的 messages 模式只会吐一个整块
        "streaming": True,
        "stream_usage": True,
        "tags": [f"stage:{config.get('stage', 'unknown')}"],
    }
    if params.get("max_tokens"):
        kwargs["max_tokens"] = int(params["max_tokens"])
    return ChatOpenAI(**kwargs)


def get_chat_model(stage: str) -> Any:
    """环境变量里的单一 provider（无绑定时兜底，也是测试 monkeypatch 的入口）。"""
    assert_provider_ready()
    settings = get_settings()
    return build_chat_model(
        {
            "stage": stage,
            "endpoint": settings.llm_endpoint,
            "model": settings.llm_model,
            "params": {"temperature": settings.llm_temperature},
        },
        settings.llm_key_deepseek,
    )
