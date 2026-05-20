from __future__ import annotations

import io
import wave

from app.domain.errors import BadRequestError


SUPPORTED_AUDIO_MIME_TYPES: dict[str, str] = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
}


def validate_audio_input(audio_bytes: bytes, mime_type: str) -> None:
    if not audio_bytes:
        raise BadRequestError("Audio input cannot be empty.")
    if mime_type not in SUPPORTED_AUDIO_MIME_TYPES:
        raise BadRequestError(
            "Unsupported audio content type.",
            details={"supported_types": sorted(SUPPORTED_AUDIO_MIME_TYPES)},
        )


def extension_for_mime_type(mime_type: str) -> str:
    extension = SUPPORTED_AUDIO_MIME_TYPES.get(mime_type)
    if not extension:
        raise BadRequestError(
            "Unsupported audio content type.",
            details={"supported_types": sorted(SUPPORTED_AUDIO_MIME_TYPES)},
        )
    return extension


def estimate_duration_ms(audio_bytes: bytes, mime_type: str) -> int | None:
    if mime_type not in {"audio/wav", "audio/x-wav"}:
        return None
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as handle:
            frame_rate = handle.getframerate()
            frame_count = handle.getnframes()
            if frame_rate <= 0:
                return None
            return int((frame_count / frame_rate) * 1000)
    except wave.Error:
        return None
