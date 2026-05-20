from uuid import uuid4

from app.domain.entities.rag import ExtractedBlock, ExtractedDocument
from app.ingestion.chunking import chunk_document


def test_chunk_document_preserves_structure_metadata():
    document = ExtractedDocument(
        text="Policy\n\nEligibility\n\nEmployees must request approval.\n\nManagers review requests.",
        detected_source_type="markdown",
        title="Policy",
        metadata={},
        blocks=[
            ExtractedBlock(
                id=uuid4(),
                block_type="heading",
                text="Policy",
                page_number=1,
                heading_level=1,
                section_path=["Policy"],
                order_index=0,
                parent_block_id=None,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="heading",
                text="Eligibility",
                page_number=1,
                heading_level=2,
                section_path=["Policy", "Eligibility"],
                order_index=1,
                parent_block_id=None,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Employees must request approval.",
                page_number=1,
                heading_level=None,
                section_path=["Policy", "Eligibility"],
                order_index=2,
                parent_block_id=None,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Managers review requests.",
                page_number=1,
                heading_level=None,
                section_path=["Policy", "Eligibility"],
                order_index=3,
                parent_block_id=None,
                metadata={},
            ),
        ],
        section_tree=[],
        warnings=[],
    )

    chunks = chunk_document(document=document, chunk_size=80, chunk_overlap=10)

    parent_chunks = [chunk for chunk in chunks if chunk.chunk_role == "parent"]
    child_chunks = [chunk for chunk in chunks if chunk.chunk_role == "child"]

    assert parent_chunks
    assert child_chunks
    assert parent_chunks[0].section_path == ["Policy", "Eligibility"]
    assert child_chunks[0].section_title == "Policy"
    assert child_chunks[0].subsection_title == "Eligibility"
    assert child_chunks[0].page_number == 1
