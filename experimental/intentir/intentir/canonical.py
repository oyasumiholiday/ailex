from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_address(value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def semantic_projection(value: Any) -> Any:
    """Remove presentation-only fields before content addressing."""
    if isinstance(value, dict):
        return {
            key: semantic_projection(item)
            for key, item in value.items()
            if key not in {"id", "source"}
        }
    if isinstance(value, list):
        return [semantic_projection(item) for item in value]
    return value
