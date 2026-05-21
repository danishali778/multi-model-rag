from uuid import uuid4

from app.domain.entities.rag import RetrievalCandidate
from app.storage.models.retrieval import RetrievalCandidateRow
from scripts.trace_rag_pipeline import _candidate_to_trace, _row_to_trace


def test_row_to_trace_normalizes_chunk_identifier():
    row = RetrievalCandidateRow(
        id=uuid4(),
        document_id=uuid4(),
        chunk_index=0,
        content="Customer support teams handled 6,842 inbound requests.",
        metadata={},
        title="Operational Report",
        sensitivity="internal",
        section_title="3. Customer Support and Satisfaction",
        section_path=["3. Customer Support and Satisfaction"],
        vector_score=0.91,
    )

    traced = _row_to_trace(row, preview=80)

    assert traced["chunk_id"] == str(row.id)
    assert "content_preview" in traced


def test_candidate_to_trace_preserves_parent_preview():
    candidate = RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        chunk_index=1,
        title="Operational Report",
        content="short child content",
        metadata={},
        sensitivity="internal",
        parent_content="This is the parent context that should be previewed first.",
        section_title="3. Customer Support and Satisfaction",
        section_path=["3. Customer Support and Satisfaction"],
        fused_score=0.12,
    )

    traced = _candidate_to_trace(candidate, preview=40)

    assert traced["parent_content_preview"].startswith("This is the parent context")


def test_trace_preserves_structure_metadata():
    row = RetrievalCandidateRow(
        id=uuid4(),
        document_id=uuid4(),
        chunk_index=3,
        content="TABLE I\nHeaders: Metric, Baseline, BDPP-IoT\nRow: MAE 100.27 11.21",
        metadata={"content_kind": "table_row", "structure_group_id": "table-1", "caption_label": "TABLE I"},
        title="Technical Paper",
        sensitivity="internal",
        chunk_type="table",
        section_title="X. RESULTS AND DISCUSSION",
        section_path=["X. RESULTS AND DISCUSSION"],
        fts_score=0.81,
    )

    traced = _row_to_trace(row, preview=80)

    assert traced["metadata"]["content_kind"] == "table_row"
    assert traced["metadata"]["caption_label"] == "TABLE I"
