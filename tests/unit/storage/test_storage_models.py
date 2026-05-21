from uuid import uuid4

from app.storage.models.conversation import MessageCreateInput
from app.storage.models.document import DocumentCreateInput, DocumentDetailRow
from app.storage.models.ingestion import IngestionJobUpdateInput
from app.storage.models.voice import VoiceTurnCreateInput, VoiceTurnRow


def test_repository_write_dtos_capture_core_payloads():
    document_payload = DocumentCreateInput(
        workspace_id=uuid4(),
        created_by=uuid4(),
        title="Handbook",
        source_type="markdown",
        source_uri="inline://Handbook",
        status="pending",
        sensitivity="internal",
        metadata={"department": "hr"},
    )
    message_payload = MessageCreateInput(
        conversation_id=uuid4(),
        role="assistant",
        content="Answer",
        model_profile="balanced",
        sources=[{"document_name": "Handbook"}],
        token_usage={"input_tokens": 10},
    )
    job_update = IngestionJobUpdateInput(status="processing", stage="chunk", stats={"chunk_count": 3})
    voice_payload = VoiceTurnCreateInput(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        transcript="hello world",
        stt_provider="openai",
        stt_model="gpt-4o-mini-transcribe",
    )

    assert document_payload.metadata["department"] == "hr"
    assert message_payload.sources[0]["document_name"] == "Handbook"
    assert job_update.stats["chunk_count"] == 3
    assert voice_payload.transcript == "hello world"


def test_repository_read_rows_are_structured():
    row = DocumentDetailRow.from_row(
        {
            "id": uuid4(),
            "title": "Handbook",
            "source_type": "markdown",
            "status": "indexed",
            "metadata": {"department": "hr"},
            "chunk_count": 4,
        }
    )

    assert row.title == "Handbook"
    assert row.chunk_count == 4


def test_voice_turn_row_is_structured():
    row = VoiceTurnRow.from_row(
        {
            "id": uuid4(),
            "workspace_id": uuid4(),
            "conversation_id": uuid4(),
            "user_message_id": uuid4(),
            "assistant_message_id": uuid4(),
            "input_audio_bucket": None,
            "input_audio_path": None,
            "output_audio_bucket": "voice-artifacts",
            "output_audio_path": "workspaces/x/output.mp3",
            "transcript": "hello world",
            "transcript_confidence": None,
            "input_duration_ms": 1200,
            "output_duration_ms": None,
            "stt_provider": "openai",
            "stt_model": "gpt-4o-mini-transcribe",
            "tts_provider": "openai",
            "tts_model": "gpt-4o-mini-tts",
            "metadata": {},
            "created_at": None,
            "updated_at": None,
        }
    )

    assert row.transcript == "hello world"
    assert row.output_audio_bucket == "voice-artifacts"
