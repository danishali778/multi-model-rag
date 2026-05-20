from __future__ import annotations


def normalize_transcript(text: str) -> str:
    return " ".join(text.split()).strip()
