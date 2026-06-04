import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.domain.entities.rag import RetrievalCandidate
from app.retrieval.reranker import CrossEncoderReranker, HeuristicLexicalReranker


def _candidate(content: str, *, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        chunk_index=0,
        title="Doc",
        content=content,
        metadata={},
        sensitivity="internal",
        fused_score=score,
    )


def test_heuristic_reranker_boosts_lexical_overlap():
    reranker = HeuristicLexicalReranker(SimpleNamespace(reranker_model_name="heuristic-lexical-v1"))
    candidates = [
        _candidate("Vacation request timelines and approval windows.", score=0.2),
        _candidate("Remote work policy allows three days per week.", score=0.18),
    ]

    reranked = asyncio.run(
        reranker.rerank("What is the remote work policy?", candidates)
    )

    assert reranked[0].content == "Remote work policy allows three days per week."


def test_cross_encoder_name_remains_backward_compatible_alias():
    reranker = CrossEncoderReranker(SimpleNamespace(reranker_model_name="legacy-name"))

    assert isinstance(reranker, HeuristicLexicalReranker)
    assert reranker.model_name == "legacy-name"
