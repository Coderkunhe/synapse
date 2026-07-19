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
    """
    if raw is None:
        return None
    return json.loads(raw)
