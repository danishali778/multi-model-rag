from __future__ import annotations


def bearer(token: str) -> str:
    return f"Bearer {token}"
