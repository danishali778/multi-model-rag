from __future__ import annotations


def normalize_voice_answer(text: str) -> str:
    return " ".join(text.split()).strip()
