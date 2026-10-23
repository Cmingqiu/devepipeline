"""凭证加解密。

Fernet 需要 32 字节 urlsafe-base64 key；APP_SECRET_KEY 是随机串，先 SHA-256 派生再 base64，
这样换 secret 等于换密钥（key_version 用于将来轮换）。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.exceptions import AppError

KEY_VERSION = 1


class CredentialDecryptError(AppError):
    status_code = 500
    code = "credential_decrypt_failed"


def _key(version: int) -> bytes:
    settings = get_settings()
    material = f"{settings.app_secret_key}:v{version}".encode()
    digest = hashlib.sha256(material).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str) -> tuple[bytes, int]:
    if not plaintext:
        raise ValueError("secret 不能为空")
    return Fernet(_key(KEY_VERSION)).encrypt(plaintext.encode("utf-8")), KEY_VERSION


def decrypt_secret(blob: bytes, key_version: int = KEY_VERSION) -> str:
    try:
        return Fernet(_key(key_version)).decrypt(blob).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise CredentialDecryptError("凭证解密失败（APP_SECRET_KEY 可能已更换）") from exc


def mask_secret(plaintext: str) -> str:
    """只留末 4 位，够 UI 区分是哪一把 key。"""
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"****{tail}"
