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


def test_chunk_document_groups_same_parent_across_pages():
    parent_id = uuid4()
    document = ExtractedDocument(
        text="Section body across two pages.",
        detected_source_type="pdf",
        title="Report",
        metadata={},
        blocks=[
            ExtractedBlock(
                id=parent_id,
                block_type="heading",
                text="3. Customer Support and Satisfaction",
                page_number=4,
                heading_level=1,
                section_path=["3. Customer Support and Satisfaction"],
                order_index=0,
                parent_block_id=None,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Customer support teams handled 6,842 inbound requests during the quarter.",
                page_number=4,
                heading_level=None,
                section_path=["3. Customer Support and Satisfaction"],
                order_index=1,
                parent_block_id=parent_id,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Repeat contact rate remained above the internal target at 17 percent.",
                page_number=5,
                heading_level=None,
                section_path=["3. Customer Support and Satisfaction"],
                order_index=2,
                parent_block_id=parent_id,
                metadata={},
            ),
        ],
        section_tree=[],
        warnings=[],
    )

    chunks = chunk_document(document=document, chunk_size=500, chunk_overlap=20)
    parent_chunks = [chunk for chunk in chunks if chunk.chunk_role == "parent"]
    child_chunks = [chunk for chunk in chunks if chunk.chunk_role == "child"]

    assert len(parent_chunks) == 1
    assert len(child_chunks) == 1
    assert "6,842 inbound requests" in parent_chunks[0].content
    assert "17 percent" in parent_chunks[0].content
    assert parent_chunks[0].section_path == ["3. Customer Support and Satisfaction"]


def test_chunk_document_builds_table_and_equation_specific_chunks():
    table_parent = uuid4()
    equation_parent = uuid4()
    table_id = "table-1"
    equation_id = "equation-12"
    document = ExtractedDocument(
        text="Technical paper structures",
        detected_source_type="pdf",
        title="Paper",
        metadata={},
        blocks=[
            ExtractedBlock(
                id=table_parent,
                block_type="heading",
                text="X. RESULTS AND DISCUSSION",
                page_number=10,
                heading_level=1,
                section_path=["X. RESULTS AND DISCUSSION"],
                order_index=0,
                parent_block_id=None,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="table_caption",
                text="TABLE I Comparison of Models",
                page_number=10,
                heading_level=None,
                section_path=["X. RESULTS AND DISCUSSION"],
                order_index=1,
                parent_block_id=table_parent,
                metadata={"content_kind": "table_caption", "table_id": table_id, "caption_label": "TABLE I"},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="table_row",
                text="MAE 100.27 11.21",
                page_number=10,
                heading_level=None,
                section_path=["X. RESULTS AND DISCUSSION"],
                order_index=2,
                parent_block_id=table_parent,
                metadata={"content_kind": "table_row", "table_id": table_id, "table_headers": ["Metric", "Baseline", "BDPP-IoT"], "row_index": 0},
            ),
            ExtractedBlock(
                id=equation_parent,
                block_type="equation",
                text="Improvement% = 88.8128% (50)",
                page_number=11,
                heading_level=None,
                section_path=["X. RESULTS AND DISCUSSION"],
                order_index=3,
                parent_block_id=table_parent,
                metadata={"content_kind": "equation", "equation_id": equation_id, "equation_label": "50"},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="equation_explanation",
                text="where Improvement measures performance gain over the baseline.",
                page_number=11,
                heading_level=None,
                section_path=["X. RESULTS AND DISCUSSION"],
                order_index=4,
                parent_block_id=table_parent,
                metadata={"content_kind": "equation_explanation", "equation_id": equation_id},
            ),
        ],
        section_tree=[],
        warnings=[],
    )

    chunks = chunk_document(document=document, chunk_size=300, chunk_overlap=20)

    table_parent_chunk = next(chunk for chunk in chunks if chunk.chunk_role == "parent" and chunk.chunk_type == "table")
    table_child_chunk = next(chunk for chunk in chunks if chunk.chunk_role == "child" and chunk.metadata.get("content_kind") == "table_row")
    equation_parent_chunk = next(chunk for chunk in chunks if chunk.chunk_role == "parent" and chunk.chunk_type == "equation")
    equation_child_chunk = next(chunk for chunk in chunks if chunk.chunk_role == "child" and chunk.metadata.get("content_kind") == "equation_explanation")

    assert "TABLE I Comparison of Models" in table_parent_chunk.content
    assert "Headers: Metric, Baseline, BDPP-IoT" in table_child_chunk.content
    assert "Row: MAE 100.27 11.21" in table_child_chunk.content
    assert table_child_chunk.metadata["structure_group_id"] == table_id
    assert "Improvement% = 88.8128% (50)" in equation_parent_chunk.content
    assert "where Improvement measures performance gain" in equation_child_chunk.content
    assert equation_child_chunk.metadata["equation_label"] == "50"
