from uuid import uuid4

from app.core.config import Settings
from app.domain.entities.rag import RetrievalCandidate
from app.retrieval.retriever import (
    _assemble_context,
    _deduplicate_candidates,
    _merge_candidates,
    _rewrite_query,
    _should_rewrite,
)
from app.storage.models.retrieval import RetrievalCandidateRow


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        supabase_db_url="postgresql://example",
        supabase_jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        groq_api_key="groq-key",
        hf_api_token="hf-key",
        redis_url="redis://localhost:6379/0",
        **overrides,
    )


def _candidate(content: str, *, document_id=None, chunk_index: int = 0, fused_score: float = 0.2) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=document_id or uuid4(),
        chunk_index=chunk_index,
        title="Doc",
        content=content,
        metadata={"department": "hr"},
        sensitivity="internal",
        fused_score=fused_score,
    )


def test_merge_candidates_prefers_hybrid_overlap():
    settings = _settings()
    shared_id = uuid4()
    doc_id = uuid4()
    vector_rows = [
        RetrievalCandidateRow(
            id=shared_id,
            document_id=doc_id,
            chunk_index=0,
            content="Remote work policy",
            metadata={},
            title="Handbook",
            sensitivity="internal",
            vector_score=0.91,
        )
    ]
    fts_rows = [
        RetrievalCandidateRow(
            id=shared_id,
            document_id=doc_id,
            chunk_index=0,
            content="Remote work policy",
            metadata={},
            title="Handbook",
            sensitivity="internal",
            fts_score=0.7,
        )
    ]

    merged = _merge_candidates(vector_rows, fts_rows, settings)

    assert len(merged) == 1
    assert merged[0].vector_score == 0.91
    assert merged[0].fts_score == 0.7
    assert merged[0].fused_score > 0


def test_should_rewrite_when_results_are_weak():
    settings = _settings(retrieval_low_score_threshold=0.05, retrieval_low_diversity_threshold=2)

    assert _should_rewrite([], settings) is True
    assert _should_rewrite([_candidate("policy", fused_score=0.01)], settings) is True


def test_rewrite_query_is_conservative():
    rewritten = _rewrite_query("What does the handbook say about remote work policy?")
    assert "remote" in rewritten
    assert "policy" in rewritten
    assert "what" not in rewritten


def test_deduplicate_candidates_removes_near_duplicates():
    document_id = uuid4()
    candidates = [
        _candidate("Remote work is allowed three days per week.", document_id=document_id, chunk_index=0),
        _candidate("Remote work is allowed three days per week!", document_id=document_id, chunk_index=1),
        _candidate("Office attendance is required on Tuesdays.", document_id=document_id, chunk_index=2),
    ]

    deduped = _deduplicate_candidates(candidates, 0.9)

    assert len(deduped) == 2


def test_context_assembly_enforces_token_budget_and_per_document_limit():
    document_id = uuid4()
    candidates = [
        _candidate("Remote work policy " * 30, document_id=document_id, chunk_index=0),
        _candidate("Remote work policy " * 30, document_id=document_id, chunk_index=1),
        _candidate("Benefits enrollment starts in June.", document_id=uuid4(), chunk_index=0),
    ]

    context = _assemble_context(
        candidates,
        requested_top_k=3,
        max_chunks_per_document=1,
        context_token_budget=220,
    )

    assert len(context.candidates) >= 1
    assert len([item for item in context.candidates if item.document_id == document_id]) == 1
    assert context.total_tokens <= 220
