"""ID generator: UUIDv7 with entity type prefix.

Format: {prefix}{uuid7_hex[:16]}
Examples: tsk_7a3b2c1d9f4e8d2a, ag_3c7b1e5f9a2d6f3c, tea_9f4e8d2a1b6c3e7f
"""

from uuid6 import uuid7

# Prefix mapping per data-model.md §8
PREFIXES: dict[str, str] = {
    "team": "tea",
    "member": "mem",
    "worker": "ag",
    "capability": "cap",
    "project": "prj",
    "task": "tsk",
    "batch": "bat",
    "verification": "ver",
    "event": "evt",
    "continuity_snapshot": "csnap",
    "analysis_record": "anl",
    "scan_result": "scn",
    "skill": "skl",
    "token_usage": "tku",
    "user": "usr",
    "user_auth_method": "uam",
    "refresh_token": "rtk",
    "password_reset_token": "prt",
    "project_actor_role": "par",  # P10-B18
    "authorization_request": "areq",  # P10-B21
    "workflow": "wfl",  # P10-B24
    "workflow_role": "wfr",  # P10-B24
    "task_worker_conversation": "twc",  # P10-B28
    "protection_report": "prpt",  # P10-B35
    "circuit_breaker": "cb",  # P10-B35
    "decision_audit": "da",  # P10-B35
    "user_push_subscription": "ups",  # P10-B44
}


def derive_id(source: str, entity_type: str) -> str:
    """从源字符串确定性派生子 ID — 数据迁移用，确保幂等。

    用途：member_id → user_id / worker_id 的可复现映射。
    ``source`` 使用稳定的标识符（如 member.id）以保证跨环境一致性。

    示例：
        derive_id("mem_019f6e082ec370b6", "user") → "usr_a1b2c3d4e5f6g7h8"
    """
    import hashlib

    prefix = PREFIXES[entity_type]
    h = hashlib.sha256(source.encode()).hexdigest()[:16]
    return f"{prefix}_{h}"


def generate_id(entity_type: str) -> str:
    """Generate a prefixed ID for the given entity type.

    Args:
        entity_type: One of the keys in PREFIXES (e.g. "task", "worker").

    Returns:
        Prefixed ID string like "tsk_7a3b2c1d".

    Raises:
        KeyError: If entity_type is not a known prefix.
    """
    prefix = PREFIXES[entity_type]
    # Use 16 hex chars (64 bits) to include random portion of UUIDv7.
    # 8 chars (32 bits) only covers the timestamp → collisions within same ms.
    short_uuid = uuid7().hex[:16]
    return f"{prefix}_{short_uuid}"
