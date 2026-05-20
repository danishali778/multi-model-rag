from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.domain.entities.rag import (
    ContextAssemblyResult,
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalRequest,
)
from app.storage.models.retrieval import RetrievalCandidateRow


class RetrievalService:
    def __init__(
        self,
        *,
        retrieval_repository: Any,
        model_router: Any,
        reranker: Any,
        settings: Any,
    ) -> None:
        self._retrieval_repository = retrieval_repository
        self._model_router = model_router
        self._reranker = reranker
        self._settings = settings

    async def retrieve(self, request: RetrievalRequest) -> RetrievalDecision:
        query_text = request.question.strip()
        vector_rows: list[dict[str, Any]] = []
        if query_text:
            query_embedding = (await self._model_router.embed_texts([query_text])).vectors[0]
            vector_rows = await self._retrieval_repository.search_vector_candidates(
                workspace_id=request.workspace_id,
                user_id=request.user_id,
                query_embedding=query_embedding,
                limit=getattr(self._settings, "retrieval_vector_candidate_count", 24),
                filters=request.filters,
                sensitivity_ceiling=request.sensitivity_ceiling,
            )

        fts_rows = await self._retrieval_repository.search_fts_candidates(
            workspace_id=request.workspace_id,
            user_id=request.user_id,
            query_text=query_text,
            limit=getattr(self._settings, "retrieval_fts_candidate_count", 24),
            filters=request.filters,
            sensitivity_ceiling=request.sensitivity_ceiling,
        )

        candidates = _merge_candidates(vector_rows, fts_rows, self._settings)
        rewrite_used = False
        no_source_reason: str | None = None

        if _should_rewrite(candidates, self._settings):
            rewritten = _rewrite_query(query_text)
            if rewritten and rewritten != query_text:
                rewrite_used = True
                query_embedding = (await self._model_router.embed_texts([rewritten])).vectors[0]
                vector_rows = await self._retrieval_repository.search_vector_candidates(
                    workspace_id=request.workspace_id,
                    user_id=request.user_id,
                    query_embedding=query_embedding,
                    limit=getattr(self._settings, "retrieval_vector_candidate_count", 24),
                    filters=request.filters,
                    sensitivity_ceiling=request.sensitivity_ceiling,
                )
                fts_rows = await self._retrieval_repository.search_fts_candidates(
                    workspace_id=request.workspace_id,
                    user_id=request.user_id,
                    query_text=rewritten,
                    limit=getattr(self._settings, "retrieval_fts_candidate_count", 24),
                    filters=request.filters,
                    sensitivity_ceiling=request.sensitivity_ceiling,
                )
                candidates = _merge_candidates(vector_rows, fts_rows, self._settings)

        reranker_used = False
        if candidates:
            reranked = await self._reranker.rerank(query_text, list(candidates))
            reranker_used = reranked is not candidates
            candidates = list(reranked)

        candidates = _deduplicate_candidates(
            candidates,
            getattr(self._settings, "retrieval_dedup_similarity_threshold", 0.92),
        )
        await self._hydrate_parent_context(candidates)
        context = _assemble_context(
            candidates,
            requested_top_k=request.requested_top_k,
            max_chunks_per_document=getattr(self._settings, "retrieval_max_chunks_per_document", 2),
            context_token_budget=getattr(self._settings, "retrieval_context_token_budget", 2200),
        )
        selected_sources = context.candidates
        if not selected_sources:
            no_source_reason = await self._retrieval_repository.diagnose_empty_retrieval(
                workspace_id=request.workspace_id,
                user_id=request.user_id,
                query_text=query_text,
                filters=request.filters,
                sensitivity_ceiling=request.sensitivity_ceiling,
            )

        return RetrievalDecision(
            selected_sources=selected_sources,
            context=context,
            retrieval_mode="hybrid",
            rewrite_used=rewrite_used,
            reranker_used=reranker_used,
            no_source_reason=no_source_reason,
            candidate_counts={
                "vector": len(vector_rows),
                "fts": len(fts_rows),
                "selected": len(selected_sources),
            },
            retrieval_config_version=getattr(self._settings, "retrieval_config_version", "hybrid-v1"),
            reranker_model=getattr(self._reranker, "model_name", None),
        )

    async def _hydrate_parent_context(self, candidates: Sequence[RetrievalCandidate]) -> None:
        parent_ids = [candidate.parent_block_id for candidate in candidates if candidate.parent_block_id is not None]
        if not parent_ids:
            return
        hydrated = await self._retrieval_repository.get_parent_context_chunks(parent_ids)
        for candidate in candidates:
            if candidate.parent_block_id is None:
                continue
            parent = hydrated.get(candidate.parent_block_id)
            if not parent:
                continue
            candidate.parent_content = parent.content or candidate.parent_content
            candidate.page_number = candidate.page_number or parent.page_number
            candidate.chunk_type = candidate.chunk_type or parent.chunk_type
            candidate.section_title = candidate.section_title or parent.section_title
            candidate.subsection_title = candidate.subsection_title or parent.subsection_title
            candidate.section_path = candidate.section_path or list(parent.section_path or [])


def _merge_candidates(
    vector_rows: Sequence[RetrievalCandidateRow],
    fts_rows: Sequence[RetrievalCandidateRow],
    settings: Any,
) -> list[RetrievalCandidate]:
    merged: dict[UUID, RetrievalCandidate] = {}
    rank_constant = max(1, getattr(settings, "retrieval_fusion_rank_constant", 60))
    vector_weight = float(getattr(settings, "retrieval_vector_weight", 1.0))
    fts_weight = float(getattr(settings, "retrieval_fts_weight", 0.85))

    for index, row in enumerate(vector_rows, start=1):
        candidate = merged.get(row.id)
        score = vector_weight / (rank_constant + index)
        if candidate is None:
            merged[row.id] = _candidate_from_row(row, vector_score=row.vector_score, fts_score=None, fused_score=score)
            continue
        candidate.vector_score = row.vector_score
        candidate.fused_score += score

    for index, row in enumerate(fts_rows, start=1):
        candidate = merged.get(row.id)
        score = fts_weight / (rank_constant + index)
        if candidate is None:
            merged[row.id] = _candidate_from_row(row, vector_score=None, fts_score=row.fts_score, fused_score=score)
            continue
        candidate.fts_score = row.fts_score
        candidate.fused_score += score

    return sorted(merged.values(), key=lambda item: item.fused_score, reverse=True)


def _candidate_from_row(
    row: RetrievalCandidateRow,
    *,
    vector_score: float | None,
    fts_score: float | None,
    fused_score: float,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=row.id,
        document_id=row.document_id,
        chunk_index=row.chunk_index,
        title=row.title,
        content=row.content,
        metadata=row.metadata or {},
        sensitivity=row.sensitivity or "internal",
        parent_block_id=row.parent_block_id,
        page_number=row.page_number,
        chunk_type=row.chunk_type,
        section_title=row.section_title,
        subsection_title=row.subsection_title,
        section_path=list(row.section_path or []),
        vector_score=vector_score,
        fts_score=fts_score,
        fused_score=fused_score,
    )


def _should_rewrite(candidates: Sequence[RetrievalCandidate], settings: Any) -> bool:
    if not candidates:
        return True
    low_score_threshold = float(getattr(settings, "retrieval_low_score_threshold", 0.018))
    low_diversity_threshold = int(getattr(settings, "retrieval_low_diversity_threshold", 2))
    best_score = max(candidate.fused_score for candidate in candidates)
    unique_documents = len({candidate.document_id for candidate in candidates})
    return best_score < low_score_threshold or unique_documents < low_diversity_threshold


def _rewrite_query(query: str) -> str:
    stop_words = {
        "a",
        "an",
        "and",
        "about",
        "does",
        "is",
        "say",
        "the",
        "what",
        "which",
        "who",
        "why",
        "how",
    }
    tokens = [token.strip(".,!?;:-_()[]{}'\"").lower() for token in query.split()]
    filtered = [token for token in tokens if token and token not in stop_words]
    return " ".join(filtered)


def _deduplicate_candidates(
    candidates: Sequence[RetrievalCandidate],
    similarity_threshold: float,
) -> list[RetrievalCandidate]:
    deduped: list[RetrievalCandidate] = []
    for candidate in candidates:
        if any(_candidate_similarity(candidate, existing) >= similarity_threshold for existing in deduped):
            continue
        deduped.append(candidate)
    return deduped


def _candidate_similarity(left: RetrievalCandidate, right: RetrievalCandidate) -> float:
    if left.parent_block_id and left.parent_block_id == right.parent_block_id:
        return 1.0
    left_terms = set(_terms(left.parent_content or left.content))
    right_terms = set(_terms(right.parent_content or right.content))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _assemble_context(
    candidates: Sequence[RetrievalCandidate],
    *,
    requested_top_k: int,
    max_chunks_per_document: int,
    context_token_budget: int,
) -> ContextAssemblyResult:
    selected: list[RetrievalCandidate] = []
    source_blocks: list[str] = []
    dropped_reasons: list[str] = []
    per_document_counts: dict[UUID, int] = {}
    total_tokens = 0

    for candidate in candidates:
        current_count = per_document_counts.get(candidate.document_id, 0)
        if current_count >= max_chunks_per_document:
            dropped_reasons.append("per_document_limit")
            continue
        source_block = _render_source_block(len(selected) + 1, candidate)
        estimated_tokens = max(1, len(source_block) // 4)
        if source_blocks and total_tokens + estimated_tokens > context_token_budget:
            dropped_reasons.append("token_budget")
            continue
        selected.append(candidate)
        source_blocks.append(source_block)
        per_document_counts[candidate.document_id] = current_count + 1
        total_tokens += estimated_tokens
        if len(selected) >= requested_top_k:
            break

    return ContextAssemblyResult(
        candidates=selected,
        source_blocks=source_blocks,
        total_tokens=total_tokens,
        dropped_reasons=dropped_reasons,
    )


def _render_source_block(source_id: int, candidate: RetrievalCandidate) -> str:
    lines = [f"[source:{source_id}] Document: {candidate.title}"]
    if candidate.section_path:
        lines.append(f"Section Path: {' > '.join(candidate.section_path)}")
    elif candidate.section_title:
        lines.append(f"Section: {candidate.section_title}")
    if candidate.subsection_title and candidate.subsection_title != candidate.section_title:
        lines.append(f"Subsection: {candidate.subsection_title}")
    if candidate.page_number is not None:
        lines.append(f"Page: {candidate.page_number}")
    if candidate.chunk_type:
        lines.append(f"Chunk Type: {candidate.chunk_type}")
    lines.append("")
    lines.append(candidate.parent_content or candidate.content)
    return "\n".join(lines)


def _terms(text: str) -> list[str]:
    words = [token.strip(".,!?;:-_()[]{}'\"").lower() for token in text.split()]
    normalized = [word for word in words if len(word) > 2]
    counts = Counter(normalized)
    return [word for word, _ in counts.most_common()]
