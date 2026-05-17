from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from difflib import SequenceMatcher
import re
from uuid import UUID

from app.core.config import Settings
from app.domain.entities.rag import (
    ContextAssemblyResult,
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalRequest,
)
from app.llm.token_counter import count_tokens
from app.retrieval.reranker import BaseReranker
from app.storage.repositories.rag import RagRepository


class RetrievalService:
    def __init__(self, *, repository: RagRepository, model_router, reranker: BaseReranker, settings: Settings):
        self.repository = repository
        self.model_router = model_router
        self.reranker = reranker
        self.settings = settings

    async def retrieve(self, request: RetrievalRequest) -> RetrievalDecision:
        normalized_question = _normalize_query(request.question)
        query_embedding = await self.model_router.embed_texts([normalized_question])
        vector_rows = await self.repository.search_vector_candidates(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            query_embedding=query_embedding.vectors[0],
            limit=self.settings.retrieval_vector_candidate_count,
            filters=request.filters,
            sensitivity_ceiling=request.sensitivity_ceiling or self.settings.retrieval_sensitivity_ceiling,
        )
        fts_rows = await self.repository.search_fts_candidates(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            query_text=normalized_question,
            limit=self.settings.retrieval_fts_candidate_count,
            filters=request.filters,
            sensitivity_ceiling=request.sensitivity_ceiling or self.settings.retrieval_sensitivity_ceiling,
        )

        merged = _merge_candidates(vector_rows, fts_rows, self.settings)
        rewrite_used = False
        if _should_rewrite(merged, self.settings):
            rewritten = _rewrite_query(normalized_question)
            if rewritten and rewritten != normalized_question:
                rewrite_used = True
                fts_rows = await self.repository.search_fts_candidates(
                    tenant_id=request.tenant_id,
                    user_id=request.user_id,
                    query_text=rewritten,
                    limit=self.settings.retrieval_fts_candidate_count,
                    filters=request.filters,
                    sensitivity_ceiling=request.sensitivity_ceiling or self.settings.retrieval_sensitivity_ceiling,
                )
                merged = _merge_candidates(vector_rows, fts_rows, self.settings)

        deduped = _deduplicate_candidates(merged, self.settings.retrieval_dedup_similarity_threshold)
        reranker_used = bool(self.settings.reranker_enabled and self.reranker.model_name)
        ranked = deduped
        if reranker_used:
            rerank_pool = deduped[: self.settings.reranker_top_n]
            remainder = deduped[self.settings.reranker_top_n :]
            ranked = await self.reranker.rerank(normalized_question, rerank_pool)
            ranked.extend(remainder)
        context = _assemble_context(
            ranked,
            requested_top_k=request.requested_top_k,
            max_chunks_per_document=self.settings.retrieval_max_chunks_per_document,
            context_token_budget=self.settings.retrieval_context_token_budget,
        )
        no_source_reason = None
        if not context.candidates:
            no_source_reason = await self.repository.diagnose_empty_retrieval(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                query_text=normalized_question,
                filters=request.filters,
                sensitivity_ceiling=request.sensitivity_ceiling or self.settings.retrieval_sensitivity_ceiling,
            )

        return RetrievalDecision(
            selected_sources=context.candidates,
            context=context,
            retrieval_mode="hybrid_fts_vector",
            rewrite_used=rewrite_used,
            reranker_used=reranker_used,
            no_source_reason=no_source_reason,
            candidate_counts={
                "vector": len(vector_rows),
                "fts": len(fts_rows),
                "merged": len(merged),
                "selected": len(context.candidates),
            },
            retrieval_config_version=self.settings.retrieval_config_version,
            reranker_model=self.reranker.model_name,
        )


def _merge_candidates(
    vector_rows: list[dict],
    fts_rows: list[dict],
    settings: Settings,
) -> list[RetrievalCandidate]:
    merged: dict[tuple[str, str], RetrievalCandidate] = {}
    rank_constant = settings.retrieval_fusion_rank_constant

    for rank, row in enumerate(vector_rows, start=1):
        key = (str(row["id"]), str(row["document_id"]))
        candidate = merged.setdefault(key, _candidate_from_row(row))
        candidate.vector_score = float(row["vector_score"])
        candidate.fused_score += settings.retrieval_vector_weight / (rank_constant + rank)

    for rank, row in enumerate(fts_rows, start=1):
        key = (str(row["id"]), str(row["document_id"]))
        candidate = merged.setdefault(key, _candidate_from_row(row))
        candidate.fts_score = float(row["fts_score"])
        candidate.fused_score += settings.retrieval_fts_weight / (rank_constant + rank)

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            item.fused_score,
            item.vector_score or 0.0,
            item.fts_score or 0.0,
        ),
        reverse=True,
    )
    return ranked


def _candidate_from_row(row: dict) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=row["id"],
        document_id=row["document_id"],
        chunk_index=int(row["chunk_index"]),
        title=row["title"],
        content=row["content"],
        metadata=row.get("metadata", {}),
        sensitivity=row["sensitivity"],
    )


def _should_rewrite(candidates: list[RetrievalCandidate], settings: Settings) -> bool:
    if not candidates:
        return True
    top_score = candidates[0].fused_score
    unique_documents = {candidate.document_id for candidate in candidates[: settings.max_context_chunks]}
    return top_score < settings.retrieval_low_score_threshold or len(unique_documents) < settings.retrieval_low_diversity_threshold


def _rewrite_query(question: str) -> str:
    terms = [token for token in re.split(r"\W+", question.lower()) if len(token) > 2]
    stopwords = {"what", "does", "say", "about", "with", "from", "that", "this", "when", "where", "which", "have", "your"}
    reduced = [term for term in terms if term not in stopwords]
    return " ".join(reduced) or question


def _normalize_query(question: str) -> str:
    collapsed = " ".join(question.split())
    return collapsed.strip()


def _deduplicate_candidates(
    candidates: list[RetrievalCandidate],
    similarity_threshold: float,
) -> list[RetrievalCandidate]:
    deduped: list[RetrievalCandidate] = []
    for candidate in candidates:
        duplicate = False
        for existing in deduped:
            if candidate.document_id == existing.document_id and candidate.chunk_index == existing.chunk_index:
                duplicate = True
                break
            if candidate.document_id == existing.document_id:
                ratio = SequenceMatcher(None, candidate.content, existing.content).ratio()
                if ratio >= similarity_threshold:
                    duplicate = True
                    break
        if not duplicate:
            deduped.append(candidate)
    return deduped


def _assemble_context(
    candidates: list[RetrievalCandidate],
    *,
    requested_top_k: int,
    max_chunks_per_document: int,
    context_token_budget: int,
) -> ContextAssemblyResult:
    selected: list[RetrievalCandidate] = []
    source_blocks: list[str] = []
    dropped_reasons: list[str] = []
    token_total = 0
    per_document: defaultdict = defaultdict(int)

    for candidate in candidates:
        if len(selected) >= requested_top_k:
            dropped_reasons.append("top_k_limit")
            break
        if per_document[candidate.document_id] >= max_chunks_per_document:
            dropped_reasons.append("per_document_limit")
            continue
        block = (
            f"[source:{len(selected) + 1} document_id={candidate.document_id} "
            f"chunk_id={candidate.chunk_id} title={candidate.title}]\n{candidate.content}"
        )
        block_tokens = count_tokens(block)
        if token_total + block_tokens > context_token_budget:
            dropped_reasons.append("context_token_budget")
            continue
        selected.append(candidate)
        source_blocks.append(block)
        token_total += block_tokens
        per_document[candidate.document_id] += 1

    return ContextAssemblyResult(
        candidates=selected,
        source_blocks=source_blocks,
        total_tokens=token_total,
        dropped_reasons=dropped_reasons,
    )


def decision_to_metadata(decision: RetrievalDecision) -> dict:
    return {
        "retrieval_mode": decision.retrieval_mode,
        "rewrite_used": decision.rewrite_used,
        "reranker_used": decision.reranker_used,
        "candidate_counts": decision.candidate_counts,
        "no_source_reason": decision.no_source_reason,
        "retrieval_config_version": decision.retrieval_config_version,
        "reranker_model": decision.reranker_model,
        "selected_sources": [_json_safe(asdict(candidate)) for candidate in decision.selected_sources],
        "context_tokens": decision.context.total_tokens,
        "dropped_reasons": decision.context.dropped_reasons,
    }


def _json_safe(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
