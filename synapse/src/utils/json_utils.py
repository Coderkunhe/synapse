"""Shared JSON serialization helpers.

Centralized safe_dumps/safe_loads to eliminate duplicated
_dump_meta / _load_meta / _dump_json / _load_json across services.
"""

from __future__ import annotations

import json
from typing import Any


def safe_dumps(obj: Any) -> str | None:
    """Serialize an object to JSON string. Returns None for None input.

    Usage:
        task.metadata_ = safe_dumps(body.metadata)
        tags_col = safe_dumps(tags)
    """
    if obj is None:
        return None
    return json.dumps(obj)


def safe_loads(raw: str | None) -> Any:
    """Deserialize a JSON string. Returns None for None/empty input.

    Usage:
        metadata = safe_loads(task.metadata_)
        tags = safe_loads(task.tags)

    P11-B67: Catches JSONDecodeError to prevent 500 errors when DB
    contains non-JSON data (e.g. tags stored as plain string
    ``"B65,permission,gap"`` instead of ``'["B65","permission","gap"]'``).
    Returns None for invalid JSON so the API can still respond.
    """
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
