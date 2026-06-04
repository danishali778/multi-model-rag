from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter

from app.core.config import Settings
from app.domain.entities.rag import RetrievalCandidate


class BaseReranker(ABC):
    @abstractmethod
    async def rerank(self, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str | None:
        raise NotImplementedError


class NoopReranker(BaseReranker):
    @property
    def model_name(self) -> str | None:
        return None

    async def rerank(self, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        return candidates


class HeuristicLexicalReranker(BaseReranker):
    """Lightweight lexical reranker used as a heuristic relevance boost."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def model_name(self) -> str | None:
        return self.settings.reranker_model_name

    async def rerank(self, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        if not candidates:
            return candidates
        ranked: list[tuple[float, RetrievalCandidate]] = []
        query_terms = _terms(query)
        for candidate in candidates:
            candidate_terms = _terms(candidate.content)
            overlap = len(set(query_terms) & set(candidate_terms))
            lexical_score = overlap / max(len(set(query_terms)), 1)
            candidate.fused_score += lexical_score * 0.25
            ranked.append((candidate.fused_score, candidate))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in ranked]


class CrossEncoderReranker(HeuristicLexicalReranker):
    """Backward-compatible alias for the legacy reranker name."""


def _terms(text: str) -> list[str]:
    words = [token.strip(".,!?;:-_()[]{}'\"").lower() for token in text.split()]
    normalized = [word for word in words if len(word) > 2]
    counts = Counter(normalized)
    return [word for word, _ in counts.most_common()]
