from typing import Any


def sanitize_metadata_filters(filters: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in filters.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
            continue
        if isinstance(value, list):
            items = [item for item in value if isinstance(item, (str, int, float, bool))]
            if items:
                sanitized[key] = items
            continue
        if isinstance(value, dict):
            nested = sanitize_metadata_filters(value)
            if nested:
                sanitized[key] = nested
    return sanitized
