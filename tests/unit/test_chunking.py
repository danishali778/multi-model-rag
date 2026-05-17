from app.ingestion.chunking import chunk_text


def test_chunk_text_preserves_metadata():
    chunks = chunk_text(
        "Heading\n\nThis is a test document with enough words to create a chunk.",
        chunk_size=30,
        chunk_overlap=5,
        base_metadata={"tenant_id": "t1", "document_id": "d1"},
    )
    assert chunks
    assert chunks[0].metadata["tenant_id"] == "t1"
    assert chunks[0].metadata["document_id"] == "d1"
    assert chunks[0].token_count > 0
