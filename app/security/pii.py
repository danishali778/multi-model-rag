from __future__ import annotations

import re
from typing import Any

EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PHONE_RE = re.compile(r"\b(?:\+?\d[\d .()-]{7,}\d)\b")
TOKEN_KEYWORDS = ("token", "secret", "password", "authorization", "api_key", "key")


def redact_text(text: str, max_length: int = 200) -> str:
    redacted = EMAIL_RE.sub("[redacted-email]", text)
    redacted = PHONE_RE.sub("[redacted-phone]", redacted)
    if len(redacted) > max_length:
        return f"{redacted[:max_length]}..."
    return redacted


def redact_value(value: Any, *, key: str | None = None, max_text_length: int = 200) -> Any:
    lowered_key = (key or "").lower()
    if any(token in lowered_key for token in TOKEN_KEYWORDS):
        return "[redacted-secret]"
    if isinstance(value, str):
        return redact_text(value, max_length=max_text_length)
    if isinstance(value, dict):
        return {item_key: redact_value(item_value, key=item_key, max_text_length=max_text_length) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_value(item, key=key, max_text_length=max_text_length) for item in value]
    return value


def redact_payload(payload: dict[str, Any], *, max_text_length: int = 200) -> dict[str, Any]:
    return {
        key: redact_value(value, key=key, max_text_length=max_text_length)
        for key, value in payload.items()
    }
