"""安全工具 — 密码哈希/验证 + Email 格式校验。

P10-B9: Email/Password 认证基础设施。使用 bcrypt 直接哈希，不依赖 passlib
（passlib 自 2020 年未更新，与 bcrypt>=4.1 不兼容）。
"""

from __future__ import annotations

import re

import bcrypt

# ── 密码常量 ────────────────────────────────────────────────────────────────

PASSWORD_MIN_LENGTH = 8
"""密码最小长度（字节）。"""

# ── Email 校验 ──────────────────────────────────────────────────────────────

# RFC 5322 simplified: local-part@domain.tld
# Requires at least one dot in the domain (TLD) — rejects
# non-deliverable addresses like "user@domain" or "admin@localhost".
_EMAIL_RE = re.compile(
    r'^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}'
    r'[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$'
)


def is_valid_email(email: str) -> bool:
    """简化的 RFC 5322 邮箱格式校验。"""
    return bool(_EMAIL_RE.match(email))


# ── 密码操作 ────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """bcrypt 哈希密码，自动生成 salt。

    bcrypt 内部限制 72 字节；调用方应在传入前截断或校验。
    返回 bcrypt hash 字符串（60 字符）。
    """
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > 72:
        pw_bytes = pw_bytes[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """bcrypt 验证密码是否与哈希匹配。"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
