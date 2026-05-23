from uuid import uuid4

from app.domain.entities.rag import ExtractedBlock, ExtractedDocument
from app.ingestion.chunking import chunk_document, chunk_document_graph
from app.ingestion.parsers.markdown import MarkdownParser


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
                metadata={
                    "content_kind": "table_caption",
                    "table_id": table_id,
                    "caption_label": "TABLE I",
                    "table_parse_status": "row_backed",
                    "docling_table_shape": "dataframe",
                },
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
                metadata={
                    "content_kind": "table_row",
                    "table_id": table_id,
                    "table_headers": ["Metric", "Baseline", "BDPP-IoT"],
                    "row_index": 0,
                    "table_parse_status": "row_backed",
                    "docling_table_shape": "dataframe",
                },
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
    assert table_child_chunk.metadata["table_parse_status"] == "row_backed"
    assert "Improvement% = 88.8128% (50)" in equation_parent_chunk.content
    assert "where Improvement measures performance gain" in equation_child_chunk.content
    assert equation_child_chunk.metadata["equation_label"] == "50"


def test_chunk_document_handles_row_backed_markdown_tables_without_special_case_logic():
    parser = MarkdownParser()
    document = parser.parse(
        b"# Handbook\n\n## Regional Policy\n\nTable 1 - Team Coverage\n\n| Team | Days |\n| --- | --- |\n| Support | 3 |\n| Field | 2 |\n",
        {"filename": "handbook.md"},
    )

    chunks = chunk_document(document=document, chunk_size=300, chunk_overlap=20)

    table_parent = next(chunk for chunk in chunks if chunk.chunk_role == "parent" and chunk.chunk_type == "table")
    table_rows = [chunk for chunk in chunks if chunk.chunk_role == "child" and chunk.metadata.get("content_kind") == "table_row"]

    assert table_parent.section_path == ["Handbook", "Regional Policy"]
    assert len(table_rows) == 2
    assert any("Headers: Team, Days" in chunk.content for chunk in table_rows)
    assert any("Row: Team: Support | Days: 3" in chunk.content for chunk in table_rows)


def test_audio_transcript_segment_metadata_survives_chunking_and_embedding_text():
    document = ExtractedDocument(
        text="Welcome everyone.\n\nDeployment starts now.",
        detected_source_type="audio",
        title="Daily Briefing",
        metadata={"source_type": "audio"},
        blocks=[
            ExtractedBlock(
                id=uuid4(),
                block_type="heading",
                text="Audio Transcript",
                page_number=None,
                heading_level=1,
                section_path=["Audio Transcript"],
                order_index=0,
                parent_block_id=None,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Welcome everyone.",
                page_number=None,
                heading_level=None,
                section_path=["Audio Transcript"],
                order_index=1,
                parent_block_id=None,
                metadata={"content_kind": "audio_transcript_segment", "segment_index": 0, "start_ms": 0, "end_ms": 1800},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Deployment starts now.",
                page_number=None,
                heading_level=None,
                section_path=["Audio Transcript"],
                order_index=2,
                parent_block_id=None,
                metadata={"content_kind": "audio_transcript_segment", "segment_index": 1, "start_ms": 1900, "end_ms": 4600},
            ),
        ],
        section_tree=[],
        warnings=[],
    )

    result = chunk_document_graph(
        document=document,
        chunk_size=300,
        chunk_overlap=20,
        base_metadata={"source_type": "audio"},
        chunking_version="hybrid-graph-v1",
    )

    child_chunks = [chunk for chunk in result.chunks if chunk.chunk_role == "child"]

    assert len(child_chunks) == 2
    assert child_chunks[0].metadata["start_ms"] == 0
    assert child_chunks[0].metadata["end_ms"] == 1800
    assert "Transcript Timing: 0ms to 1800ms" in (child_chunks[0].embedding_text or "")
    assert child_chunks[0].next_chunk_id == child_chunks[1].id


def test_chunk_document_skips_front_matter_blocks_marked_for_exclusion():
    document = ExtractedDocument(
        text="Paper",
        detected_source_type="pdf",
        title="Paper",
        metadata={},
        blocks=[
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Danish Ali Department of Artificial Intelligence",
                page_number=1,
                heading_level=None,
                section_path=[],
                order_index=0,
                parent_block_id=None,
                metadata={
                    "content_kind": "front_matter",
                    "exclude_from_chunking": True,
                    "exclude_from_retrieval": True,
                },
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="heading",
                text="Abstract",
                page_number=1,
                heading_level=1,
                section_path=["Abstract"],
                order_index=1,
                parent_block_id=None,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="This paper proposes a privacy-preserving framework.",
                page_number=1,
                heading_level=None,
                section_path=["Abstract"],
                order_index=2,
                parent_block_id=None,
                metadata={"content_kind": "paragraph"},
            ),
        ],
        section_tree=[],
        warnings=[],
    )

    chunks = chunk_document(document=document, chunk_size=200, chunk_overlap=20)

    assert all("Danish Ali" not in chunk.content for chunk in chunks)
    assert any("privacy-preserving framework" in chunk.content for chunk in chunks)


def test_hybrid_graph_chunking_builds_section_nodes_and_chunk_links():
    section_id = uuid4()
    subsection_id = uuid4()
    document = ExtractedDocument(
        text="Methodology and chunking details.",
        detected_source_type="pdf",
        title="Multi-Model RAG",
        metadata={},
        blocks=[
            ExtractedBlock(
                id=section_id,
                block_type="heading",
                text="3. Methodology",
                page_number=7,
                heading_level=1,
                section_path=["3. Methodology"],
                order_index=0,
                parent_block_id=None,
                metadata={},
            ),
            ExtractedBlock(
                id=subsection_id,
                block_type="heading",
                text="3.2 Chunking",
                page_number=7,
                heading_level=2,
                section_path=["3. Methodology", "3.2 Chunking"],
                order_index=1,
                parent_block_id=section_id,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Chunking groups structurally related blocks into retrievable units.",
                page_number=7,
                heading_level=None,
                section_path=["3. Methodology", "3.2 Chunking"],
                order_index=2,
                parent_block_id=subsection_id,
                metadata={},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="paragraph",
                text="Neighbor links provide local continuity for expansion.",
                page_number=8,
                heading_level=None,
                section_path=["3. Methodology", "3.2 Chunking"],
                order_index=3,
                parent_block_id=subsection_id,
                metadata={},
            ),
        ],
        section_tree=[],
        warnings=[],
    )

    result = chunk_document_graph(
        document=document,
        chunk_size=20,
        chunk_overlap=0,
        base_metadata={"title": "Multi-Model RAG", "source_type": "pdf"},
        chunking_version="hybrid-graph-v1",
    )

    section_nodes = [node for node in result.nodes if node.node_type == "section"]
    prose_nodes = [node for node in result.nodes if node.node_type == "prose_group"]
    child_chunks = [chunk for chunk in result.chunks if chunk.chunk_role == "child"]

    assert len(section_nodes) == 2
    assert len(prose_nodes) == 1
    assert prose_nodes[0].parent_node_id == section_nodes[-1].id
    assert child_chunks[0].node_id == prose_nodes[0].id
    assert child_chunks[0].next_chunk_id == child_chunks[1].id
    assert child_chunks[1].previous_chunk_id == child_chunks[0].id
    assert "Section Path: 3. Methodology > 3.2 Chunking" in child_chunks[0].embedding_text
    assert child_chunks[0].page_start == 7
    assert child_chunks[0].page_end == 8


def test_hybrid_graph_chunking_attaches_table_rows_to_table_node():
    heading_id = uuid4()
    table_id = "table-1"
    document = ExtractedDocument(
        text="Results table",
        detected_source_type="pdf",
        title="Paper",
        metadata={},
        blocks=[
            ExtractedBlock(
                id=heading_id,
                block_type="heading",
                text="X. RESULTS",
                page_number=10,
                heading_level=1,
                section_path=["X. RESULTS"],
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
                section_path=["X. RESULTS"],
                order_index=1,
                parent_block_id=heading_id,
                metadata={"content_kind": "table_caption", "table_id": table_id, "caption_label": "TABLE I"},
            ),
            ExtractedBlock(
                id=uuid4(),
                block_type="table_row",
                text="Metric: MAE | Baseline: 100.27 | Model: 11.21",
                page_number=10,
                heading_level=None,
                section_path=["X. RESULTS"],
                order_index=2,
                parent_block_id=heading_id,
                metadata={
                    "content_kind": "table_row",
                    "table_id": table_id,
                    "table_headers": ["Metric", "Baseline", "Model"],
                    "row_index": 0,
                },
            ),
        ],
        section_tree=[],
        warnings=[],
    )

    result = chunk_document_graph(
        document=document,
        chunk_size=300,
        chunk_overlap=0,
        base_metadata={"title": "Paper", "source_type": "pdf"},
        chunking_version="hybrid-graph-v1",
    )

    table_node = next(node for node in result.nodes if node.node_type == "table")
    table_row_chunk = next(chunk for chunk in result.chunks if chunk.metadata.get("content_kind") == "table_row")

    assert table_row_chunk.node_id == table_node.id
    assert table_row_chunk.parent_node_id == table_node.parent_node_id
    assert "Table: TABLE I" in table_row_chunk.embedding_text
    assert "Headers: Metric, Baseline, Model" in table_row_chunk.embedding_text
