from __future__ import annotations

from uuid import UUID

from app.domain.entities.rag import ContextAssemblyResult, RetrievalCandidate
from app.retrieval.retriever import _extract_query_features, _merge_candidates


class AudioRetrievalService:
    def __init__(self, *, retrieval_repository, model_router, settings) -> None:
        self._retrieval_repository = retrieval_repository
        self._model_router = model_router
        self._settings = settings

    async def retrieve(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        query_text: str,
        document_ids: list[UUID] | None = None,
        top_k: int = 4,
        sensitivity_ceiling: str | None = None,
    ) -> ContextAssemblyResult:
        filters = {"content_kind": "audio_transcript_segment"}
        if document_ids:
            filters["document_ids"] = document_ids
        embedding_result = await self._model_router.embed_texts([query_text])
        vector_candidates = await self._retrieval_repository.search_vector_candidates(
            workspace_id=workspace_id,
            user_id=user_id,
            query_embedding=embedding_result.vectors[0],
            limit=max(top_k * 3, 6),
            filters=filters,
            sensitivity_ceiling=sensitivity_ceiling,
        )
        fts_candidates = await self._retrieval_repository.search_fts_candidates(
            workspace_id=workspace_id,
            user_id=user_id,
            query_text=query_text,
            limit=max(top_k * 3, 6),
            filters=filters,
            sensitivity_ceiling=sensitivity_ceiling,
        )
        merged = _merge_candidates(vector_candidates, fts_candidates, self._settings)
        seeded = self._apply_audio_boosts(merged, query_text=query_text)
        neighbors = await self._retrieval_repository.get_neighboring_chunks(
            workspace_id=workspace_id,
            user_id=user_id,
            chunk_ids=[candidate.chunk_id for candidate in seeded[:top_k]],
            sensitivity_ceiling=sensitivity_ceiling,
        )
        neighbor_map = {candidate.id: candidate for candidate in neighbors}
        expanded: list[RetrievalCandidate] = []
        for seed in seeded[:top_k]:
            seed.selection_role = "primary_seed"
            expanded.append(seed)
            for neighbor_id in (seed.previous_chunk_id, seed.next_chunk_id):
                if neighbor_id and neighbor_id in neighbor_map:
                    support = _candidate_from_row(neighbor_map[neighbor_id])
                    support.selection_role = "local_support"
                    support.fused_score = max(seed.fused_score - 0.01, 0.01)
                    expanded.append(support)
        selected: list[RetrievalCandidate] = []
        seen_chunk_ids: set[UUID] = set()
        for candidate in expanded:
            if candidate.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(candidate.chunk_id)
            selected.append(candidate)
        source_blocks = [candidate.content for candidate in selected]
        total_tokens = sum(max(1, len(candidate.content.split())) for candidate in selected)
        return ContextAssemblyResult(
            candidates=selected,
            source_blocks=source_blocks,
            total_tokens=total_tokens,
            dropped_reasons=[],
            assembly_policy={"mode": "audio_neighbors"},
        )

    def _apply_audio_boosts(
        self,
        candidates: list[RetrievalCandidate],
        *,
        query_text: str,
    ) -> list[RetrievalCandidate]:
        features = _extract_query_features(query_text)
        boosted: list[RetrievalCandidate] = []
        for candidate in candidates:
            boost = 0.0
            if candidate.metadata.get("content_kind") == "audio_transcript_segment":
                boost += 0.05
            if candidate.metadata.get("start_ms") is not None and candidate.metadata.get("end_ms") is not None:
                boost += 0.02
            if features.get("has_number") and candidate.metadata.get("start_ms") is not None:
                boost += 0.01
            candidate.fused_score += boost
            boosted.append(candidate)
        return sorted(boosted, key=lambda item: item.fused_score, reverse=True)


def _candidate_from_row(row) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=row.id,
        document_id=row.document_id,
        chunk_index=row.chunk_index,
        title=row.title,
        content=row.content,
        metadata=row.metadata,
        sensitivity=row.sensitivity,
        parent_block_id=row.parent_block_id,
        page_number=row.page_number,
        chunk_type=row.chunk_type,
        section_title=row.section_title,
        subsection_title=row.subsection_title,
        section_path=list(row.section_path or []),
        node_id=row.node_id,
        parent_node_id=row.parent_node_id,
        previous_chunk_id=row.previous_chunk_id,
        next_chunk_id=row.next_chunk_id,
        level=row.level,
        page_start=row.page_start,
        page_end=row.page_end,
        chunking_version=row.chunking_version,
    )
