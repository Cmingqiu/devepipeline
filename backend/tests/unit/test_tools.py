from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.tools import resolve_credentials, tool_name
from app.core.security import encrypt_secret


def test_tool_name_prefixes_and_sanitizes() -> None:
    assert tool_name("fs", "read_file") == "fs__read_file"
    assert tool_name("my server", "read.file") == "my_server__read_file"
    long_name = tool_name("server", "x" * 120)
    assert len(long_name) == 64


class _FakeSession:
    def __init__(self, credentials: dict[int, SimpleNamespace]) -> None:
        self._credentials = credentials

    async def get(self, model, credential_id):
        return self._credentials.get(credential_id)


async def test_resolve_credentials_replaces_placeholders() -> None:
    blob, version = encrypt_secret("secret-token")
    session = _FakeSession({7: SimpleNamespace(encrypted_blob=blob, key_version=version, project_id=3)})

    config = {
        "env": {"TOKEN": "$CRED:7", "PLAIN": "abc"},
        "args": ["--token", "$CRED:7"],
    }
    resolved = await resolve_credentials(session, 3, config)  # type: ignore[arg-type]

    assert resolved["env"]["TOKEN"] == "secret-token"
    assert resolved["env"]["PLAIN"] == "abc"
    assert resolved["args"] == ["--token", "secret-token"]


async def test_resolve_credentials_rejects_foreign_project() -> None:
    blob, version = encrypt_secret("other-token")
    session = _FakeSession({9: SimpleNamespace(encrypted_blob=blob, key_version=version, project_id=99)})
    with pytest.raises(ValueError):
        await resolve_credentials(session, 3, {"env": {"TOKEN": "$CRED:9"}})  # type: ignore[arg-type]


async def test_resolve_credentials_missing_id() -> None:
    session = _FakeSession({})
    with pytest.raises(ValueError):
        await resolve_credentials(session, 3, {"headers": {"Authorization": "$CRED:404"}})  # type: ignore[arg-type]


async def test_non_placeholder_strings_untouched() -> None:
    session = _FakeSession({})
    assert await resolve_credentials(session, 1, {"x": "value"}) == {"x": "value"}  # type: ignore[arg-type]
