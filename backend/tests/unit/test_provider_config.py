from __future__ import annotations

import pytest

from app.agents.llm import ProviderNotConfigured, build_chat_model
from app.core.exceptions import SemanticError
from app.services.provider_service import env_key_name, normalize_endpoint


def test_normalize_endpoint_appends_chat_suffix():
    assert (
        normalize_endpoint("https://api.deepseek.com")
        == "https://api.deepseek.com/chat/completions"
    )
    assert (
        normalize_endpoint("https://api.deepseek.com/chat/completions/")
        == "https://api.deepseek.com/chat/completions"
    )
    with pytest.raises(SemanticError):
        normalize_endpoint("   ")


def test_env_key_name():
    assert env_key_name("deepseek-v4-flash") == "LLM_KEY_DEEPSEEK_V4_FLASH"
    assert env_key_name("my.provider") == "LLM_KEY_MY_PROVIDER"


def test_build_chat_model_uses_config(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_temperature", 0.2, raising=False)
    model = build_chat_model(
        {
            "stage": "analysis",
            "endpoint": "https://api.example.com/chat/completions",
            "model": "gpt-test",
            "params": {"temperature": 0.7, "max_tokens": 128},
        },
        "sk-test",
    )
    assert model.model_name == "gpt-test"
    assert model.temperature == 0.7
    assert model.max_tokens == 128
    assert "api.example.com" in str(model.openai_api_base)

    with pytest.raises(ProviderNotConfigured):
        build_chat_model(
            {"stage": "analysis", "endpoint": "https://x/chat/completions", "model": "m"},
            "",
        )
