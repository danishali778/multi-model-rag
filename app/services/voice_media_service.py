from __future__ import annotations

from uuid import UUID, uuid4

from app.domain.errors import BadRequestError
from app.storage.object_store import StorageClient
from app.voice.audio_formats import estimate_duration_ms, extension_for_mime_type, validate_audio_input
from app.voice.schemas import VoiceInputReference, VoiceOutputArtifact


class VoiceMediaService:
    def __init__(self, *, storage: StorageClient, settings):
        self._storage = storage
        self._settings = settings

    async def load_audio_bytes(
        self,
        *,
        audio_bytes: bytes | None,
        mime_type: str | None,
        filename: str | None,
        upload_bucket: str | None,
        upload_path: str | None,
    ) -> tuple[bytes, str, str, int | None]:
        if audio_bytes is not None:
            if not mime_type:
                raise BadRequestError("Audio content type is required for uploaded audio.")
            validate_audio_input(audio_bytes, mime_type)
            resolved_name = filename or f"voice-input.{extension_for_mime_type(mime_type)}"
            return audio_bytes, mime_type, resolved_name, estimate_duration_ms(audio_bytes, mime_type)

        if not upload_path:
            raise BadRequestError("Either an audio file upload or audio storage reference is required.")
        bucket = upload_bucket or self._settings.supabase_voice_bucket
        resolved_mime_type = mime_type or _mime_type_from_path(upload_path)
        downloaded = await self._storage.download_bytes(bucket=bucket, path=upload_path)
        validate_audio_input(downloaded, resolved_mime_type)
        return downloaded, resolved_mime_type, upload_path.rsplit("/", 1)[-1], estimate_duration_ms(downloaded, resolved_mime_type)

    async def maybe_store_input_audio(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID,
        audio_bytes: bytes,
        mime_type: str,
        filename: str,
    ) -> VoiceInputReference | None:
        if not getattr(self._settings, "voice_store_raw_input_audio", False):
            return None
        extension = extension_for_mime_type(mime_type)
        path = (
            f"workspaces/{workspace_id}/conversations/{conversation_id}/voice/input/"
            f"{uuid4()}-{filename.rsplit('.', 1)[0]}.{extension}"
        )
        await self._storage.upload_bytes(
            bucket=self._settings.supabase_voice_bucket,
            path=path,
            raw_bytes=audio_bytes,
            content_type=mime_type,
        )
        return VoiceInputReference(
            bucket=self._settings.supabase_voice_bucket,
            path=path,
            mime_type=mime_type,
            filename=filename,
        )

    async def store_output_audio(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID,
        assistant_message_id: UUID,
        audio_bytes: bytes,
        audio_format: str,
    ) -> VoiceOutputArtifact:
        content_type = _content_type_for_format(audio_format)
        path = (
            f"workspaces/{workspace_id}/conversations/{conversation_id}/voice/output/"
            f"{assistant_message_id}.{audio_format}"
        )
        await self._storage.upload_bytes(
            bucket=self._settings.supabase_voice_bucket,
            path=path,
            raw_bytes=audio_bytes,
            content_type=content_type,
        )
        url = await self._storage.create_signed_download_url(
            bucket=self._settings.supabase_voice_bucket,
            path=path,
            expires_in=getattr(self._settings, "voice_signed_url_ttl_seconds", 3600),
        )
        return VoiceOutputArtifact(
            bucket=self._settings.supabase_voice_bucket,
            path=path,
            url=url,
            format=audio_format,
            duration_ms=None,
        )


def _mime_type_from_path(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".wav"):
        return "audio/wav"
    if lowered.endswith(".mp3"):
        return "audio/mpeg"
    if lowered.endswith(".webm"):
        return "audio/webm"
    if lowered.endswith(".ogg"):
        return "audio/ogg"
    if lowered.endswith(".m4a") or lowered.endswith(".mp4"):
        return "audio/mp4"
    raise BadRequestError("Unsupported audio file reference.")


def _content_type_for_format(audio_format: str) -> str:
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
    }.get(audio_format, "audio/mpeg")
