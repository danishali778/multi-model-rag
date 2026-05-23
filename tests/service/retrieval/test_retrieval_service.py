import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.core.config import Settings
from app.domain.entities.rag import RetrievalCandidate
from app.retrieval.retriever import (
    RetrievalService,
    _apply_structural_boosts,
    _assemble_context,
    _classify_query,
    _deduplicate_candidates,
    _extract_query_features,
    _merge_candidates,
    _query_strategy,
    _rewrite_query,
    _should_rewrite,
    _should_use_graph_retrieval,
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


def test_structural_boosts_prefer_section_overlap():
    exact = _candidate("Repeat contact rate remained above target.", fused_score=0.02)
    exact.section_title = "3. Customer Support and Satisfaction"
    exact.section_path = ["3. Customer Support and Satisfaction"]
    broad = _candidate("Modernization should focus on reducing operational ambiguity.", fused_score=0.03)
    broad.section_title = "8. Modernization Priorities"
    broad.section_path = ["8. Modernization Priorities"]

    boosted = _apply_structural_boosts(
        [broad, exact],
        "Why did repeat contacts remain above target according to the report?",
    )

    assert boosted[0].section_title == "3. Customer Support and Satisfaction"


def test_query_classification_detects_numeric_and_summary_modes():
    numeric_features = _extract_query_features("What happened to manual reporting exceptions from Q4 2024 to Q1 2025?")
    summary_features = _extract_query_features("Summarize the report's executive summary in two or three sentences.")

    assert _classify_query("What happened to manual reporting exceptions from Q4 2024 to Q1 2025?", numeric_features) == "numeric_detail"
    assert _classify_query("Summarize the report's executive summary in two or three sentences.", summary_features) == "summary"


def test_query_strategy_biases_fts_for_numeric_questions():
    settings = _settings()
    features = _extract_query_features("Which training program was furthest behind target completion at 68 percent?")

    strategy = _query_strategy(
        query_text="Which training program was furthest behind target completion at 68 percent?",
        query_class="numeric_detail",
        query_features=features,
        requested_top_k=4,
        settings=settings,
    )

    assert strategy["fts_weight"] > strategy["vector_weight"]
    assert strategy["allow_rewrite"] is False
    assert strategy["max_chunks_per_document"] == 1


def test_context_assembly_prefers_section_diversity_for_compare_questions():
    doc_id = uuid4()
    first = _candidate("Strategic segment has 38 accounts and 96.4 percent retention.", document_id=doc_id, chunk_index=0, fused_score=0.2)
    first.section_title = "Client Portfolio Snapshot"
    first.section_path = ["1. Organizational Context", "Client Portfolio Snapshot"]
    duplicate = _candidate("Strategic segment implementation support details.", document_id=doc_id, chunk_index=1, fused_score=0.19)
    duplicate.section_title = "Client Portfolio Snapshot"
    duplicate.section_path = ["1. Organizational Context", "Client Portfolio Snapshot"]
    second = _candidate("Core segment has 84 accounts and 91.9 percent retention.", document_id=doc_id, chunk_index=2, fused_score=0.18)
    second.section_title = "Core Segment"
    second.section_path = ["1. Organizational Context", "Core Segment"]

    context = _assemble_context(
        [first, duplicate, second],
        requested_top_k=3,
        max_chunks_per_document=3,
        context_token_budget=400,
        section_diversity_target=2,
        support_sections_target=2,
        min_incremental_terms=1,
        prefer_diversity=True,
        query_class="compare",
    )

    assert [item.section_title for item in context.candidates] == ["Client Portfolio Snapshot", "Core Segment"]
    assert "duplicate_section" in context.dropped_reasons


def test_structural_boosts_prefer_table_rows_for_metric_queries():
    table_row = _candidate("TABLE I\nHeaders: Metric, Baseline, BDPP-IoT\nRow: MAE 100.27 11.21", fused_score=0.02)
    table_row.metadata = {"content_kind": "table_row", "caption_label": "TABLE I"}
    prose = _candidate("The results section discusses several improvements over baseline.", fused_score=0.03)
    prose.metadata = {"content_kind": "paragraph"}

    boosted = _apply_structural_boosts(
        [prose, table_row],
        "What value does Table I report for MAE?",
        query_features=_extract_query_features("What value does Table I report for MAE?"),
    )

    assert boosted[0].metadata["content_kind"] == "table_row"


def test_context_assembly_avoids_table_row_spam_for_summary_queries():
    document_id = uuid4()
    row_one = _candidate("Row: MAE 100.27 11.21", document_id=document_id, chunk_index=0, fused_score=0.21)
    row_one.metadata = {"content_kind": "table_row", "structure_group_id": "table-1"}
    row_one.section_title = "X. RESULTS"
    row_one.section_path = ["X. RESULTS"]
    row_two = _candidate("Row: R2 -4.27 0.89", document_id=document_id, chunk_index=1, fused_score=0.2)
    row_two.metadata = {"content_kind": "table_row", "structure_group_id": "table-1"}
    row_two.section_title = "X. RESULTS"
    row_two.section_path = ["X. RESULTS"]
    prose = _candidate("The proposed model substantially improves predictive quality.", document_id=document_id, chunk_index=2, fused_score=0.19)
    prose.metadata = {"content_kind": "paragraph"}
    prose.section_title = "XV. CONCLUSION"
    prose.section_path = ["XV. CONCLUSION"]

    context = _assemble_context(
        [row_one, row_two, prose],
        requested_top_k=3,
        max_chunks_per_document=3,
        context_token_budget=500,
        section_diversity_target=2,
        support_sections_target=2,
        min_incremental_terms=0,
        prefer_diversity=True,
        query_class="summary",
    )

    assert len([item for item in context.candidates if item.metadata.get("content_kind") == "table_row"]) == 1
    assert any(item.section_title == "XV. CONCLUSION" for item in context.candidates)


def test_graph_context_assembly_limits_same_node_repetition():
    node_id = uuid4()
    parent_node_id = uuid4()
    seed = _candidate("Chunking preserves section-local continuity.", chunk_index=0, fused_score=0.3)
    seed.node_id = node_id
    seed.parent_node_id = parent_node_id
    seed.chunking_version = "hybrid-graph-v1"
    seed.metadata = {"graph_relation": "seed", "content_kind": "paragraph"}

    support = _candidate("Neighbor chunks add local context around the seed.", chunk_index=1, fused_score=0.28)
    support.node_id = node_id
    support.parent_node_id = parent_node_id
    support.chunking_version = "hybrid-graph-v1"
    support.metadata = {"graph_relation": "neighbor", "content_kind": "paragraph"}

    extra = _candidate("A third same-node chunk should be dropped for fact queries.", chunk_index=2, fused_score=0.27)
    extra.node_id = node_id
    extra.parent_node_id = parent_node_id
    extra.chunking_version = "hybrid-graph-v1"
    extra.metadata = {"graph_relation": "same_node_child", "content_kind": "paragraph"}

    ancestor = _candidate("Section summary gives broader methodological framing.", chunk_index=3, fused_score=0.26)
    ancestor.node_id = uuid4()
    ancestor.parent_node_id = uuid4()
    ancestor.chunking_version = "hybrid-graph-v1"
    ancestor.metadata = {"graph_relation": "ancestor_parent", "content_kind": "section_summary"}

    context = _assemble_context(
        [seed, support, extra, ancestor],
        requested_top_k=4,
        max_chunks_per_document=4,
        context_token_budget=600,
        query_class="fact",
        graph_enabled=True,
    )

    assert len([item for item in context.candidates if item.node_id == node_id]) == 2
    assert any(item.selection_role == "ancestor_context" for item in context.candidates)


def test_should_use_graph_retrieval_requires_graph_version_and_nodes():
    settings = _settings(retrieval_config_version="hybrid-graph-v1")
    candidate = _candidate("Chunked content")
    candidate.node_id = uuid4()
    candidate.chunking_version = "hybrid-graph-v1"

    assert _should_use_graph_retrieval([candidate], settings) is True
    candidate.chunking_version = "recursive-v1"
    assert _should_use_graph_retrieval([candidate], settings) is False


class _GraphRepo:
    async def get_chunks_by_node_ids(self, *, workspace_id, user_id, node_ids, chunk_role, sensitivity_ceiling):
        rows = []
        if chunk_role == "parent":
            for node_id in node_ids:
                rows.append(
                    RetrievalCandidateRow(
                        id=uuid4(),
                        document_id=uuid4(),
                        chunk_index=10,
                        content="Parent summary for node",
                        metadata={"content_kind": "section_summary"},
                        title="Doc",
                        sensitivity="internal",
                        node_id=node_id,
                        chunking_version="hybrid-graph-v1",
                    )
                )
        return rows

    async def get_neighboring_chunks(self, *, workspace_id, user_id, chunk_ids, sensitivity_ceiling):
        return [
            RetrievalCandidateRow(
                id=uuid4(),
                document_id=uuid4(),
                chunk_index=11,
                content="Immediate neighbor child chunk",
                metadata={"content_kind": "paragraph"},
                title="Doc",
                sensitivity="internal",
                node_id=uuid4(),
                chunking_version="hybrid-graph-v1",
            )
        ]

    async def get_ancestor_nodes(self, *, workspace_id, user_id, node_ids, max_depth=2):
        return []

    async def get_nodes_by_ids(self, *, workspace_id, user_id, node_ids):
        return {}

    async def get_sibling_nodes(self, *, workspace_id, user_id, node_ids):
        return []


def test_graph_expansion_adds_parent_and_neighbor_candidates():
    service = RetrievalService(
        retrieval_repository=_GraphRepo(),
        model_router=SimpleNamespace(),
        reranker=SimpleNamespace(),
        settings=SimpleNamespace(retrieval_config_version="hybrid-graph-v1"),
    )
    seed = RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        chunk_index=0,
        title="Doc",
        content="Seed chunk",
        metadata={"content_kind": "paragraph", "graph_relation": "seed"},
        sensitivity="internal",
        fused_score=0.3,
        node_id=uuid4(),
        chunking_version="hybrid-graph-v1",
    )

    expanded = asyncio.run(
        service._expand_graph_candidates(
            candidates=[seed],
            workspace_id=uuid4(),
            user_id=uuid4(),
            sensitivity_ceiling=None,
            query_class="fact",
            query_features={"has_table_terms": False, "has_equation_terms": False},
        )
    )

    relations = {item.metadata.get("graph_relation") for item in expanded}
    assert "same_node_parent" in relations
    assert "neighbor" in relations
