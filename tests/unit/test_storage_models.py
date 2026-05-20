from uuid import uuid4

from app.storage.models.conversation import MessageCreateInput
from app.storage.models.document import DocumentCreateInput, DocumentDetailRow
from app.storage.models.ingestion import IngestionJobUpdateInput


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
    assert document_payload.metadata["department"] == "hr"
    assert message_payload.sources[0]["document_name"] == "Handbook"
    assert job_update.stats["chunk_count"] == 3


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
