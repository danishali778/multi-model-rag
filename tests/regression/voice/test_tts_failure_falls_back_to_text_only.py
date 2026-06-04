import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas.voice import VoiceChatRequest
from app.domain.entities.rag import Principal
from app.domain.errors import ProviderUnavailableError
from app.services.chat_service import ChatTurnResult
from app.services.voice_chat_service import VoiceChatService


async def _transcribe_audio(**kwargs):
    return SimpleNamespace(
        transcript="hello world",
        confidence=0.9,
        provider="openai",
        model_name="gpt-4o-mini-transcribe",
        input_duration_ms=1000,
    )


async def _failing_tts(**kwargs):
    raise ProviderUnavailableError("tts down")


async def _answer_text_turn(**kwargs):
    return ChatTurnResult(
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        answer="Answer",
        sources=[],
        model="groq:mock-model",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1, estimated_cost_usd=0.0),
        metadata={},
    )


def test_tts_failure_keeps_text_answer_and_sets_metadata_flag():
    async def fake_create_voice_turn(payload):
        return uuid4()

    async def fake_load_audio_bytes(**kwargs):
        return b"audio", "audio/wav", "turn.wav", 1000

    async def fake_store_input_audio(**kwargs):
        return None

    service = VoiceChatService(
        conversation_repository=SimpleNamespace(),
        voice_repository=SimpleNamespace(create_voice_turn=fake_create_voice_turn),
        chat_service=SimpleNamespace(answer_text_turn=_answer_text_turn),
        voice_media_service=SimpleNamespace(
            load_audio_bytes=fake_load_audio_bytes,
            maybe_store_input_audio=fake_store_input_audio,
            store_output_audio=fake_store_input_audio,
        ),
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

    response = asyncio.run(
        service.answer_voice_turn(
            workspace_id=uuid4(),
            principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key"),
            payload=VoiceChatRequest(profile="balanced"),
            audio_bytes=b"audio",
            audio_filename="turn.wav",
        )
    )

    assert response.answer == "Answer"
    assert response.assistant_audio_url is None
    assert response.metadata["voice_tts_failure"] == "tts down"
