from __future__ import annotations

import pytest

from app.agents.llm import ProviderNotConfigured, assert_provider_ready, to_base_url


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://api.deepseek.com/chat/completions", "https://api.deepseek.com"),
        ("https://api.deepseek.com/chat/completions/", "https://api.deepseek.com"),
        ("https://api.deepseek.com/v1/chat/completions", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com", "https://api.deepseek.com"),
        ("https://api.deepseek.com/v1/", "https://api.deepseek.com/v1"),
        ("  https://example.com/chat/completions  ", "https://example.com"),
    ],
)
def test_to_base_url_strips_chat_suffix(endpoint: str, expected: str) -> None:
    assert to_base_url(endpoint) == expected


def test_assert_provider_ready_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_key_deepseek", "", raising=False)
    with pytest.raises(ProviderNotConfigured) as exc:
        assert_provider_ready()
    assert exc.value.status_code == 422


def test_assert_provider_ready_passes_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_key_deepseek", "sk-test", raising=False)
    assert_provider_ready()
