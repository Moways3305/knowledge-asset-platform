"""密码哈希服务。

标准库 PBKDF2-HMAC-SHA256，无新依赖。编码格式（server-only，绝不外泄）：

    pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64>

- salt 用 `secrets.token_bytes` 生成（16 字节）；
- 校验用 `hmac.compare_digest`（恒定时间）；
- 未知算法 / 格式非法 / 空 hash 一律返回校验失败，不抛未处理异常；
- **绝不**在日志 / 异常 / 审计中输出明文密码 / salt / digest。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 260000
_SALT_BYTES = 16
_MIN_LENGTH = 8


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str) -> str:
    """生成 `pbkdf2_sha256$iter$salt$digest` 编码哈希（server-only）。"""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _pbkdf2(password, salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    """恒定时间校验。空 hash / 格式非法 / 未知算法 → False（不抛异常）。"""
    if not encoded or not password:
        return False
    try:
        algorithm, iter_str, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != _ALGORITHM:
            return False
        iterations = int(iter_str)
        salt = _b64d(salt_b64)
        expected = _b64d(digest_b64)
    except (ValueError, TypeError, base64.binascii.Error):  # type: ignore[attr-defined]
        return False
    candidate = _pbkdf2(password, salt, iterations)
    return hmac.compare_digest(candidate, expected)


def validate_password_strength(password: str) -> str | None:
    """最低强度校验。返回 None=合格，否则返回安全中文文案（不回显密码本身）。"""
    if password is None or len(password) < _MIN_LENGTH:
        return f"密码长度至少 {_MIN_LENGTH} 位"
    if not password.strip():
        return "密码不能全为空白字符"
    return None


# 用于"用户不存在"时的恒定时间兜底校验，避免计时旁路区分用户是否存在。
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def dummy_verify(password: str) -> None:
    """对不存在用户也跑一次 PBKDF2，均衡时间侧信道（结果丢弃）。"""
    verify_password(password or "x", _DUMMY_HASH)

