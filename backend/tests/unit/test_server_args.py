from __future__ import annotations

import pytest

from app.core.server import DEFAULT_HOST, DEFAULT_PORT, parse_args


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("API_HOST", "API_PORT", "API_RELOAD", "API_LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


def test_defaults() -> None:
    args = parse_args([])
    assert args.host == DEFAULT_HOST
    assert args.port == DEFAULT_PORT
    assert args.reload is False
    assert args.log_level == "info"


def test_env_vars_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("API_PORT", "8010")
    monkeypatch.setenv("API_RELOAD", "true")
    monkeypatch.setenv("API_LOG_LEVEL", "debug")

    args = parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 8010
    assert args.reload is True
    assert args.log_level == "debug"


def test_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_PORT", "8010")
    args = parse_args(["--port", "9001", "--host", "127.0.0.2"])
    assert args.port == 9001
    assert args.host == "127.0.0.2"


def test_bad_env_port_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_PORT", "not-a-number")
    assert parse_args([]).port == DEFAULT_PORT


def test_unknown_log_level_exits() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--log-level", "verbose"])
