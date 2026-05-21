import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas.voice import VoiceChatRequest
from app.domain.entities.rag import Principal, SourceCitation, UsageStats
from app.domain.errors import ProviderUnavailableError
from app.services.chat_service import ChatTurnResult
from app.services.voice_chat_service import VoiceChatService
from app.voice.schemas import VoiceInputReference, VoiceOutputArtifact


class _VoiceRepository:
    def __init__(self):
        self.created_payload = None

    async def create_voice_turn(self, payload):
        self.created_payload = payload
        return uuid4()


class _VoiceMediaService:
    def __init__(self):
        self.stored_input = False
        self.stored_output = False

    async def load_audio_bytes(self, **kwargs):
        return b"audio", "audio/wav", "turn.wav", 1200

    async def maybe_store_input_audio(self, **kwargs):
        self.stored_input = True
        return None

    async def store_output_audio(self, **kwargs):
        self.stored_output = True
        return VoiceOutputArtifact(
            bucket="voice-artifacts",
            path="output.mp3",
            url="https://example.com/output.mp3",
            format="mp3",
        )


class _ChatService:
    async def answer_text_turn(self, **kwargs):
        source = SourceCitation(
            source_id=1,
            document_id=uuid4(),
            chunk_id=uuid4(),
            title="Handbook",
            score=0.9,
            snippet="Remote work is allowed.",
        )
        return ChatTurnResult(
            conversation_id=uuid4(),
            user_message_id=uuid4(),
            assistant_message_id=uuid4(),
            answer="Remote work is allowed.",
            sources=[source],
            model="groq:mock-model",
            usage=UsageStats(input_tokens=12, output_tokens=8, estimated_cost_usd=0.0),
            metadata={"profile": "balanced"},
        )


async def _transcribe_audio(**kwargs):
    return SimpleNamespace(
        transcript=" Hello world ",
        confidence=0.8,
        provider="openai",
        model_name="gpt-4o-mini-transcribe",
        input_duration_ms=1300,
    )


async def _synthesize_speech(**kwargs):
    return SimpleNamespace(
        audio_bytes=b"assistant-audio",
        provider="openai",
        model_name="gpt-4o-mini-tts",
        audio_format="mp3",
    )


def test_voice_chat_service_persists_transcript_and_audio():
    repo = _VoiceRepository()
    media = _VoiceMediaService()
    service = VoiceChatService(
        conversation_repository=SimpleNamespace(),
        voice_repository=repo,
        chat_service=_ChatService(),
        voice_media_service=media,
        model_router=SimpleNamespace(transcribe_audio=_transcribe_audio, synthesize_speech=_synthesize_speech),
        security_policy=SimpleNamespace(),
        telemetry=SimpleNamespace(
            record_voice_transcription=lambda **kwargs: None,
            record_voice_synthesis=lambda **kwargs: None,
        ),
        settings=SimpleNamespace(
            voice_enabled=True,
            voice_tts_enabled=True,
            voice_tts_provider="openai",
            openai_model_tts="gpt-4o-mini-tts",
        ),
    )
    principal = Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key")

    response = asyncio.run(
        service.answer_voice_turn(
            workspace_id=uuid4(),
            principal=principal,
            payload=VoiceChatRequest(profile="balanced", metadata={"channel": "web"}),
            audio_bytes=b"audio",
            audio_filename="turn.wav",
        )
    )

    assert response.user_transcript == "Hello world"
    assert response.assistant_audio_url == "https://example.com/output.mp3"
    assert repo.created_payload.transcript == "Hello world"
    assert repo.created_payload.output_audio_bucket == "voice-artifacts"


async def _failing_tts(**kwargs):
    raise ProviderUnavailableError("tts down")


def test_voice_chat_service_degrades_when_tts_fails():
    repo = _VoiceRepository()
    media = _VoiceMediaService()
    service = VoiceChatService(
        conversation_repository=SimpleNamespace(),
        voice_repository=repo,
        chat_service=_ChatService(),
        voice_media_service=media,
        model_router=SimpleNamespace(transcribe_audio=_transcribe_audio, synthesize_speech=_failing_tts),
        security_policy=SimpleNamespace(),
        telemetry=SimpleNamespace(
            record_voice_transcription=lambda **kwargs: None,
            record_voice_synthesis=lambda **kwargs: None,
        ),
        settings=SimpleNamespace(
            voice_enabled=True,
            voice_tts_enabled=True,
            voice_tts_provider="openai",
            openai_model_tts="gpt-4o-mini-tts",
        ),
    )
    principal = Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key")

    response = asyncio.run(
        service.answer_voice_turn(
            workspace_id=uuid4(),
            principal=principal,
            payload=VoiceChatRequest(profile="balanced"),
            audio_bytes=b"audio",
            audio_filename="turn.wav",
        )
    )

    assert response.assistant_audio_url is None
    assert response.metadata["voice_tts_failure"] == "tts down"
