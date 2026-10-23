from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.security import decrypt_secret, encrypt_secret, mask_secret


def test_encrypt_roundtrip() -> None:
    blob, version = encrypt_secret("ghp_abcdef123456")
    assert version == 1
    assert blob != b"ghp_abcdef123456"
    assert decrypt_secret(blob, version) == "ghp_abcdef123456"


def test_ciphertext_is_randomized() -> None:
    first, _ = encrypt_secret("same-secret")
    second, _ = encrypt_secret("same-secret")
    assert first != second  # Fernet 带随机 IV


def test_mask_keeps_last_four() -> None:
    assert mask_secret("ghp_abcdef123456") == "****3456"
    assert mask_secret("ab") == "****ab"


def test_decrypt_fails_after_secret_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    blob, version = encrypt_secret("token")
    monkeypatch.setattr(get_settings(), "app_secret_key", "another-secret", raising=False)
    with pytest.raises(AppError):
        decrypt_secret(blob, version)


def test_empty_secret_rejected() -> None:
    with pytest.raises(ValueError):
        encrypt_secret("")
