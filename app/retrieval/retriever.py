from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import re
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
        query_features = _extract_query_features(query_text)
        query_class = _classify_query(query_text, query_features)
        strategy = _query_strategy(
            query_text=query_text,
            query_class=query_class,
            query_features=query_features,
            requested_top_k=request.requested_top_k,
            settings=self._settings,
        )
        vector_rows: list[dict[str, Any]] = []
        if query_text:
            query_embedding = (await self._model_router.embed_texts([query_text])).vectors[0]
            vector_rows = await self._retrieval_repository.search_vector_candidates(
                workspace_id=request.workspace_id,
                user_id=request.user_id,
                query_embedding=query_embedding,
                limit=strategy["vector_limit"],
                filters=request.filters,
                sensitivity_ceiling=request.sensitivity_ceiling,
            )

        fts_rows = await self._retrieval_repository.search_fts_candidates(
            workspace_id=request.workspace_id,
            user_id=request.user_id,
            query_text=query_text,
            limit=strategy["fts_limit"],
            filters=request.filters,
            sensitivity_ceiling=request.sensitivity_ceiling,
        )

        candidates = _merge_candidates(
            vector_rows,
            fts_rows,
            self._settings,
            vector_weight=strategy["vector_weight"],
            fts_weight=strategy["fts_weight"],
        )
        candidates = _apply_structural_boosts(candidates, query_text, query_features=query_features)
        rewrite_used = False
        no_source_reason: str | None = None
        rewritten_query = query_text

        if _should_rewrite(candidates, self._settings, allow_rewrite=strategy["allow_rewrite"]):
            rewritten = _rewrite_query(query_text)
            if rewritten and rewritten != query_text:
                rewrite_used = True
                rewritten_query = rewritten
                query_embedding = (await self._model_router.embed_texts([rewritten])).vectors[0]
                vector_rows = await self._retrieval_repository.search_vector_candidates(
                    workspace_id=request.workspace_id,
                    user_id=request.user_id,
                    query_embedding=query_embedding,
                    limit=strategy["vector_limit"],
                    filters=request.filters,
                    sensitivity_ceiling=request.sensitivity_ceiling,
                )
                fts_rows = await self._retrieval_repository.search_fts_candidates(
                    workspace_id=request.workspace_id,
                    user_id=request.user_id,
                    query_text=rewritten,
                    limit=strategy["fts_limit"],
                    filters=request.filters,
                    sensitivity_ceiling=request.sensitivity_ceiling,
                )
                candidates = _merge_candidates(
                    vector_rows,
                    fts_rows,
                    self._settings,
                    vector_weight=strategy["vector_weight"],
                    fts_weight=strategy["fts_weight"],
                )
                candidates = _apply_structural_boosts(candidates, rewritten, query_features=query_features)

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
            requested_top_k=strategy["requested_top_k"],
            max_chunks_per_document=strategy["max_chunks_per_document"],
            context_token_budget=strategy["context_token_budget"],
            section_diversity_target=strategy["section_diversity_target"],
            support_sections_target=strategy["support_sections_target"],
            min_incremental_terms=strategy["min_incremental_terms"],
            prefer_diversity=strategy["prefer_diversity"],
            query_class=query_class,
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
            query_class=query_class,
            strategy_name=strategy["name"],
            query_features=query_features,
            rewritten_query=rewritten_query if rewrite_used else None,
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
    *,
    vector_weight: float | None = None,
    fts_weight: float | None = None,
) -> list[RetrievalCandidate]:
    merged: dict[UUID, RetrievalCandidate] = {}
    rank_constant = max(1, getattr(settings, "retrieval_fusion_rank_constant", 60))
    vector_weight = float(vector_weight if vector_weight is not None else getattr(settings, "retrieval_vector_weight", 1.0))
    fts_weight = float(fts_weight if fts_weight is not None else getattr(settings, "retrieval_fts_weight", 0.85))

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


def _apply_structural_boosts(
    candidates: Sequence[RetrievalCandidate],
    query_text: str,
    *,
    query_features: dict[str, Any] | None = None,
) -> list[RetrievalCandidate]:
    if not candidates:
        return []

    query_terms = set(_terms(query_text))
    if not query_terms:
        return sorted(list(candidates), key=lambda item: item.fused_score, reverse=True)

    boosted: list[RetrievalCandidate] = []
    query_text_lower = query_text.lower()
    section_terms_hint = {item.lower() for item in (query_features or {}).get("section_terms", [])}
    quoted_phrase = (query_features or {}).get("quoted_phrase")
    wants_table = bool((query_features or {}).get("has_table_terms"))
    wants_equation = bool((query_features or {}).get("has_equation_terms"))
    wants_algorithm = bool((query_features or {}).get("has_algorithm_terms"))
    wants_figure = bool((query_features or {}).get("has_figure_terms"))
    for candidate in candidates:
        section_text = " ".join(
            part
            for part in [
                candidate.section_title or "",
                candidate.subsection_title or "",
                " ".join(candidate.section_path or []),
            ]
            if part
        )
        section_terms = set(_terms(section_text))
        content_terms = set(_terms(candidate.parent_content or candidate.content)[:40])
        section_overlap = len(query_terms & section_terms)
        content_overlap = len(query_terms & content_terms)
        content_kind = str(candidate.metadata.get("content_kind") or candidate.chunk_type or "").lower()

        boost = 0.0
        if section_overlap:
            boost += min(0.12, 0.03 * section_overlap)
        if content_overlap:
            boost += min(0.08, 0.01 * content_overlap)
        if section_text and section_text.lower() in query_text_lower:
            boost += 0.08
        if section_terms_hint and section_terms_hint & section_terms:
            boost += min(0.16, 0.05 * len(section_terms_hint & section_terms))
        if quoted_phrase and quoted_phrase in (candidate.parent_content or candidate.content).lower():
            boost += 0.08
        if wants_table and content_kind in {"table", "table_caption", "table_row"}:
            boost += 0.12 if content_kind == "table_row" else 0.08
        if wants_equation and content_kind in {"equation", "equation_explanation", "equation_group"}:
            boost += 0.12 if content_kind == "equation" else 0.08
        if wants_algorithm and content_kind == "algorithm":
            boost += 0.1
        if wants_figure and content_kind == "figure_caption":
            boost += 0.08
        if candidate.metadata.get("equation_label") and str(candidate.metadata["equation_label"]).lower() in query_text_lower:
            boost += 0.08
        if candidate.metadata.get("caption_label") and str(candidate.metadata["caption_label"]).lower() in query_text_lower:
            boost += 0.08
        if candidate.metadata.get("algorithm_label") and str(candidate.metadata["algorithm_label"]).lower() in query_text_lower:
            boost += 0.08

        candidate.fused_score += boost
        boosted.append(candidate)

    return sorted(boosted, key=lambda item: item.fused_score, reverse=True)


def _should_rewrite(candidates: Sequence[RetrievalCandidate], settings: Any, *, allow_rewrite: bool = True) -> bool:
    if not allow_rewrite:
        return False
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
    section_diversity_target: int = 1,
    support_sections_target: int = 1,
    min_incremental_terms: int = 0,
    prefer_diversity: bool = False,
    query_class: str = "fact",
) -> ContextAssemblyResult:
    selected: list[RetrievalCandidate] = []
    source_blocks: list[str] = []
    dropped_reasons: list[str] = []
    per_document_counts: dict[UUID, int] = {}
    selected_sections: set[str] = set()
    total_tokens = 0
    selected_structure_groups: set[str] = set()

    for candidate in candidates:
        current_count = per_document_counts.get(candidate.document_id, 0)
        if current_count >= max_chunks_per_document:
            dropped_reasons.append("per_document_limit")
            continue
        content_kind = str(candidate.metadata.get("content_kind") or candidate.chunk_type or "")
        structure_group = str(candidate.metadata.get("structure_group_id") or "") or None
        section_key = _candidate_section_key(candidate)
        if (
            prefer_diversity
            and section_key in selected_sections
            and len(selected_sections) < section_diversity_target
        ):
            dropped_reasons.append("duplicate_section")
            continue
        if (
            query_class == "summary"
            and content_kind == "table_row"
            and any(
                str(item.metadata.get("structure_group_id") or "") == str(candidate.metadata.get("structure_group_id") or "")
                for item in selected
            )
        ):
            dropped_reasons.append("low_incremental_value")
            continue
        if structure_group and structure_group in selected_structure_groups and content_kind in {"table_row", "equation"}:
            sibling_selected = any(
                str(item.metadata.get("structure_group_id") or "") == structure_group and item.chunk_id != candidate.chunk_id
                for item in selected
            )
            if sibling_selected and query_class != "compare":
                dropped_reasons.append("duplicate_section")
                continue
        if min_incremental_terms > 0 and selected and not _adds_incremental_value(candidate, selected, min_incremental_terms):
            dropped_reasons.append("low_incremental_value")
            continue
        source_block = _render_source_block(len(selected) + 1, candidate)
        estimated_tokens = max(1, len(source_block) // 4)
        if source_blocks and total_tokens + estimated_tokens > context_token_budget:
            dropped_reasons.append("token_budget")
            continue
        candidate.selection_role = _selection_role(
            candidate,
            selected=selected,
            selected_sections=selected_sections,
            support_sections_target=support_sections_target,
            query_class=query_class,
        )
        selected.append(candidate)
        source_blocks.append(source_block)
        per_document_counts[candidate.document_id] = current_count + 1
        selected_sections.add(section_key)
        if structure_group:
            selected_structure_groups.add(structure_group)
        total_tokens += estimated_tokens
        if len(selected) >= requested_top_k:
            break

    return ContextAssemblyResult(
        candidates=selected,
        source_blocks=source_blocks,
        total_tokens=total_tokens,
        dropped_reasons=dropped_reasons,
        assembly_policy={
            "query_class": query_class,
            "requested_top_k": requested_top_k,
            "max_chunks_per_document": max_chunks_per_document,
            "context_token_budget": context_token_budget,
            "section_diversity_target": section_diversity_target,
            "support_sections_target": support_sections_target,
            "prefer_diversity": prefer_diversity,
            "min_incremental_terms": min_incremental_terms,
        },
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
    if candidate.metadata.get("content_kind"):
        lines.append(f"Content Kind: {candidate.metadata['content_kind']}")
    if candidate.metadata.get("caption_label"):
        lines.append(f"Caption Label: {candidate.metadata['caption_label']}")
    if candidate.metadata.get("equation_label"):
        lines.append(f"Equation Label: {candidate.metadata['equation_label']}")
    if candidate.metadata.get("algorithm_label"):
        lines.append(f"Algorithm Label: {candidate.metadata['algorithm_label']}")
    lines.append("")
    lines.append(candidate.parent_content or candidate.content)
    return "\n".join(lines)


def _terms(text: str) -> list[str]:
    words = [token.strip(".,!?;:-_()[]{}'\"").lower() for token in text.split()]
    normalized = [word for word in words if len(word) > 2]
    counts = Counter(normalized)
    return [word for word, _ in counts.most_common()]


def _extract_query_features(query_text: str) -> dict[str, Any]:
    lowered = query_text.lower()
    tokens = _terms(query_text)
    section_terms = [term for term in ("summary", "conclusion", "phase", "risk", "governance", "support", "training", "table", "figure", "algorithm", "equation") if term in lowered]
    return {
        "has_number": bool(re.search(r"\b\d+(?:[.,]\d+)?\b", query_text)),
        "has_date": bool(re.search(r"\b(?:q[1-4]\s+\d{4}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", lowered)),
        "has_compare_terms": any(term in lowered for term in ("compare", "versus", "vs", "difference", "both", "whereas")),
        "has_summary_terms": any(term in lowered for term in ("summarize", "summary", "overview")),
        "has_conclusion_terms": any(term in lowered for term in ("conclusion", "real challenge", "main challenge")),
        "has_why_terms": any(term in lowered for term in ("why", "reason", "drivers", "cause")),
        "has_unanswerable_probe_terms": any(term in lowered for term in ("ceo", "salary", "approved", "quarterly revenue")),
        "has_table_terms": any(term in lowered for term in ("table", "metric", "mae", "r2", "value", "values", "accuracy")),
        "has_equation_terms": any(term in lowered for term in ("equation", "formula", "variable", "compute", "calculation")),
        "has_algorithm_terms": any(term in lowered for term in ("algorithm", "step", "procedure", "workflow")),
        "has_figure_terms": any(term in lowered for term in ("figure", "fig.", "fig ")),
        "section_terms": section_terms,
        "quoted_phrase": _extract_quoted_phrase(query_text),
        "top_terms": tokens[:8],
    }


def _classify_query(query_text: str, features: dict[str, Any]) -> str:
    lowered = query_text.lower()
    if features["has_unanswerable_probe_terms"]:
        return "unsupported_probe"
    if features["has_conclusion_terms"]:
        return "conclusion"
    if features["has_summary_terms"]:
        return "summary"
    if features["has_compare_terms"]:
        return "compare"
    if features["has_why_terms"]:
        return "why"
    if features["has_number"] or features["has_date"] or features["has_table_terms"] or features["has_equation_terms"] or any(term in lowered for term in ("how many", "what reporting period", "which training program", "what happened")):
        return "numeric_detail"
    return "fact"


def _query_strategy(
    *,
    query_text: str,
    query_class: str,
    query_features: dict[str, Any],
    requested_top_k: int,
    settings: Any,
) -> dict[str, Any]:
    vector_limit = int(getattr(settings, "retrieval_vector_candidate_count", 24))
    fts_limit = int(getattr(settings, "retrieval_fts_candidate_count", 24))
    vector_weight = float(getattr(settings, "retrieval_vector_weight", 1.0))
    fts_weight = float(getattr(settings, "retrieval_fts_weight", 0.85))
    base_top_k = max(1, requested_top_k)
    base_per_document = int(getattr(settings, "retrieval_max_chunks_per_document", 2))
    base_budget = int(getattr(settings, "retrieval_context_token_budget", 2200))

    strategy = {
        "name": f"query-aware-{query_class}",
        "vector_limit": vector_limit,
        "fts_limit": fts_limit,
        "vector_weight": vector_weight,
        "fts_weight": fts_weight,
        "allow_rewrite": True,
        "requested_top_k": base_top_k,
        "max_chunks_per_document": base_per_document,
        "context_token_budget": base_budget,
        "section_diversity_target": 1,
        "support_sections_target": 1,
        "prefer_diversity": False,
        "min_incremental_terms": 0,
    }

    if query_class in {"fact", "numeric_detail"}:
        strategy["vector_weight"] = 0.95 if query_class == "fact" else 0.85
        strategy["fts_weight"] = 1.1 if query_features["has_number"] or query_features["has_date"] else 1.0
        if query_features["has_table_terms"] or query_features["has_equation_terms"] or query_features["has_algorithm_terms"]:
            strategy["fts_weight"] += 0.15
        strategy["allow_rewrite"] = not (query_features["has_number"] or query_features["has_date"])
        strategy["requested_top_k"] = min(base_top_k, 2)
        strategy["max_chunks_per_document"] = 1
    elif query_class == "summary":
        strategy["vector_weight"] = 1.0
        strategy["fts_weight"] = 0.75
        strategy["requested_top_k"] = max(base_top_k, 3)
        strategy["max_chunks_per_document"] = max(base_per_document, 3)
        strategy["context_token_budget"] = int(base_budget * 1.35)
        strategy["section_diversity_target"] = 2
        strategy["support_sections_target"] = 2
        strategy["prefer_diversity"] = True
        strategy["min_incremental_terms"] = 3
    elif query_class == "compare":
        strategy["requested_top_k"] = max(base_top_k, 3)
        strategy["max_chunks_per_document"] = max(base_per_document, 2)
        strategy["section_diversity_target"] = 2
        strategy["support_sections_target"] = 2
        strategy["prefer_diversity"] = True
        strategy["min_incremental_terms"] = 2
    elif query_class in {"why", "conclusion"}:
        strategy["vector_weight"] = 1.05
        strategy["fts_weight"] = 0.8
        strategy["requested_top_k"] = max(base_top_k, 2)
        strategy["section_diversity_target"] = 2
        strategy["support_sections_target"] = 2
        strategy["prefer_diversity"] = True
        strategy["min_incremental_terms"] = 2
    elif query_class == "unsupported_probe":
        strategy["requested_top_k"] = min(base_top_k, 2)
        strategy["max_chunks_per_document"] = 1
        strategy["allow_rewrite"] = False

    if query_features["section_terms"]:
        strategy["fts_weight"] += 0.1
    if "according to" in query_text.lower():
        strategy["vector_weight"] += 0.05

    return strategy


def _extract_quoted_phrase(query_text: str) -> str | None:
    match = re.search(r"['\"]([^'\"]{3,})['\"]", query_text)
    return match.group(1).lower() if match else None


def _candidate_section_key(candidate: RetrievalCandidate) -> str:
    if candidate.section_path:
        return " > ".join(candidate.section_path).lower()
    if candidate.section_title:
        return candidate.section_title.lower()
    if candidate.subsection_title:
        return candidate.subsection_title.lower()
    return candidate.title.lower()


def _adds_incremental_value(
    candidate: RetrievalCandidate,
    selected: Sequence[RetrievalCandidate],
    min_incremental_terms: int,
) -> bool:
    candidate_terms = set(_terms(candidate.parent_content or candidate.content)[:50])
    existing_terms: set[str] = set()
    for item in selected:
        existing_terms.update(_terms(item.parent_content or item.content)[:50])
    return len(candidate_terms - existing_terms) >= min_incremental_terms


def _selection_role(
    candidate: RetrievalCandidate,
    *,
    selected: Sequence[RetrievalCandidate],
    selected_sections: set[str],
    support_sections_target: int,
    query_class: str,
) -> str:
    if not selected:
        return "primary"
    if _candidate_section_key(candidate) not in selected_sections and len(selected_sections) < support_sections_target:
        return "supporting"
    if query_class in {"summary", "compare", "why", "conclusion"}:
        return "supporting"
    return "supplemental"
