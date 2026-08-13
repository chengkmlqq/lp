from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

logger = logging.getLogger(__name__)

# 加密值前缀：enc:v1:<base64(nonce || ciphertext || tag)>
PREFIX = "enc:v1:"

# 加密参数对外展示的掩码（后台列表/详情/卡片/编辑弹窗统一使用）
MASK = "••••••••"

_NONCE_LENGTH = 12


def _derive_key() -> bytes:
    raw = get_settings().system_param_encryption_key
    if not raw:
        raise RuntimeError(
            "SYSTEM_PARAM_ENCRYPTION_KEY is not configured; cannot encrypt system params"
        )
    key_bytes = raw.encode("utf-8")
    if len(key_bytes) == 32:
        return key_bytes
    # 兼容任意长度的配置值：统一通过 SHA-256 归一化为 32 字节密钥
    return hashlib.sha256(key_bytes).digest()


def is_encrypted_value(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt_value(plaintext: str) -> str:
    """AES-256-GCM 加密，空值直接返回空串（不产生密文）。"""
    if not plaintext:
        return ""
    key = _derive_key()
    nonce = os.urandom(_NONCE_LENGTH)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_value(encoded: str) -> str | None:
    """解密密文；非本模块格式或解密失败返回 None，绝不抛异常泄露细节。"""
    if not encoded or not encoded.startswith(PREFIX):
        return None
    try:
        raw = base64.b64decode(encoded[len(PREFIX):], validate=False)
    except ValueError:
        return None
    if len(raw) <= _NONCE_LENGTH:
        return None
    nonce = raw[:_NONCE_LENGTH]
    payload = raw[_NONCE_LENGTH:]
    try:
        plaintext = AESGCM(_derive_key()).decrypt(nonce, payload, None)
    except Exception:
        logger.warning("system param decrypt failed (key mismatch or corrupt ciphertext)", exc_info=True)
        return None
    return plaintext.decode("utf-8")
