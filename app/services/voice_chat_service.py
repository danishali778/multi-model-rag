from __future__ import annotations

from uuid import UUID

from app.api.schemas.chat import SourceResponse, UsageResponse
from app.api.schemas.voice import VoiceChatRequest, VoiceChatResponse
from app.domain.entities.rag import Principal
from app.domain.errors import BadRequestError, ProviderUnavailableError
from app.services.chat_service import ChatService
from app.storage.models.voice import VoiceTurnCreateInput
from app.voice.synthesis import normalize_voice_answer
from app.voice.transcription import normalize_transcript


class VoiceChatService:
    def __init__(
        self,
        *,
        conversation_repository,
        voice_repository,
        chat_service: ChatService,
        voice_media_service,
        model_router,
        security_policy,
        telemetry,
        settings,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._voice_repository = voice_repository
        self._chat_service = chat_service
        self._voice_media_service = voice_media_service
        self._model_router = model_router
        self._security_policy = security_policy
        self._telemetry = telemetry
        self._settings = settings

    async def answer_voice_turn(
        self,
        *,
        workspace_id: UUID,
        principal: Principal,
        payload: VoiceChatRequest,
        audio_bytes: bytes | None,
        audio_filename: str | None,
    ) -> VoiceChatResponse:
        if not getattr(self._settings, "voice_enabled", True):
            raise BadRequestError("Voice chat is disabled.")

        audio_bytes, mime_type, filename, input_duration_ms = await self._voice_media_service.load_audio_bytes(
            audio_bytes=audio_bytes,
            mime_type=payload.mime_type,
            filename=audio_filename,
            upload_bucket=payload.audio_upload_bucket,
            upload_path=payload.audio_upload_path,
        )

        try:
            transcription = await self._model_router.transcribe_audio(
                audio_bytes=audio_bytes,
                mime_type=mime_type,
                filename=filename,
            )
        except ProviderUnavailableError:
            self._telemetry.record_voice_transcription(
                status="failed",
                provider=getattr(self._settings, "voice_stt_provider", "unknown"),
            )
            raise
        self._telemetry.record_voice_transcription(status="succeeded", provider=transcription.provider)
        transcript = normalize_transcript(transcription.transcript)
        if not transcript:
            raise BadRequestError("Speech-to-text returned an empty transcript.")

        text_turn = await self._chat_service.answer_text_turn(
            workspace_id=workspace_id,
            principal=principal,
            query=transcript,
            conversation_id=payload.conversation_id,
            profile=payload.profile or "balanced",
            document_ids=payload.document_ids,
        )

        stored_input = await self._voice_media_service.maybe_store_input_audio(
            workspace_id=workspace_id,
            conversation_id=text_turn.conversation_id,
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            filename=filename,
        )

        assistant_audio_url: str | None = None
        output_artifact = None
        synthesis_failure: str | None = None
        if getattr(self._settings, "voice_tts_enabled", True):
            try:
                synthesis = await self._model_router.synthesize_speech(
                    text=normalize_voice_answer(text_turn.answer),
                )
                self._telemetry.record_voice_synthesis(status="succeeded", provider=synthesis.provider)
                output_artifact = await self._voice_media_service.store_output_audio(
                    workspace_id=workspace_id,
                    conversation_id=text_turn.conversation_id,
                    assistant_message_id=text_turn.assistant_message_id,
                    audio_bytes=synthesis.audio_bytes,
                    audio_format=synthesis.audio_format,
                )
                assistant_audio_url = output_artifact.url
            except ProviderUnavailableError as exc:
                self._telemetry.record_voice_synthesis(
                    status="failed",
                    provider=getattr(self._settings, "voice_tts_provider", "unknown"),
                )
                synthesis_failure = exc.message

        voice_turn_id = await self._voice_repository.create_voice_turn(
            VoiceTurnCreateInput(
                workspace_id=workspace_id,
                conversation_id=text_turn.conversation_id,
                user_message_id=text_turn.user_message_id,
                assistant_message_id=text_turn.assistant_message_id,
                transcript=transcript,
                transcript_confidence=transcription.confidence,
                input_duration_ms=input_duration_ms or transcription.input_duration_ms,
                output_duration_ms=output_artifact.duration_ms if output_artifact else None,
                stt_provider=transcription.provider,
                stt_model=transcription.model_name,
                tts_provider=self._settings.voice_tts_provider if output_artifact else None,
                tts_model=self._settings.openai_model_tts if output_artifact else None,
                input_audio_bucket=stored_input.bucket if stored_input else None,
                input_audio_path=stored_input.path if stored_input else None,
                output_audio_bucket=output_artifact.bucket if output_artifact else None,
                output_audio_path=output_artifact.path if output_artifact else None,
                metadata={
                    **(payload.metadata or {}),
                    "mime_type": mime_type,
                    "document_ids": [str(item) for item in (payload.document_ids or [])],
                    "tts_failure": synthesis_failure,
                },
            )
        )

        metadata = {**text_turn.metadata, "voice_turn_id": str(voice_turn_id)}
        if synthesis_failure:
            metadata["voice_tts_failure"] = synthesis_failure

        return VoiceChatResponse(
            conversation_id=text_turn.conversation_id,
            message_id=text_turn.assistant_message_id,
            user_transcript=transcript,
            answer=text_turn.answer,
            assistant_audio_url=assistant_audio_url,
            sources=[
                SourceResponse(
                    chunk_id=source.chunk_id,
                    document_id=source.document_id,
                    document_name=source.title,
                    snippet=source.snippet,
                    score=source.score,
                    section_title=source.section_title,
                    subsection_title=source.subsection_title,
                    section_path=list(source.section_path),
                    page_number=source.page_number,
                    chunk_type=source.chunk_type,
                )
                for source in text_turn.sources
            ],
            model=text_turn.model,
            usage=UsageResponse(
                input_tokens=text_turn.usage.input_tokens,
                output_tokens=text_turn.usage.output_tokens,
                total_tokens=text_turn.usage.input_tokens + text_turn.usage.output_tokens,
            ),
            metadata=metadata,
        )
