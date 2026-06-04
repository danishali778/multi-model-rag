import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.domain.entities.rag import ContextAssemblyResult, RetrievalCandidate, RetrievalDecision
from app.services.evaluation_service import EvaluationService


class _Repository:
    def __init__(self):
        self.payload = None
        self.run_id = uuid4()

    async def create_evaluation_run(self, payload):
        self.payload = payload
        return self.run_id


class _RetrievalService:
    def __init__(self):
        self.requests = []

    async def retrieve(self, request):
        self.requests.append(request)
        candidate = RetrievalCandidate(
            chunk_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            document_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            chunk_index=0,
            title="Remote Work Policy",
            content="Remote work is allowed three days per week with manager approval.",
            metadata={},
            sensitivity="internal",
            fused_score=0.9,
        )
        return RetrievalDecision(
            selected_sources=[candidate],
            context=ContextAssemblyResult(
                candidates=[candidate],
                source_blocks=[candidate.content],
                total_tokens=12,
                dropped_reasons=[],
            ),
            retrieval_mode="hybrid",
            rewrite_used=False,
            reranker_used=False,
            no_source_reason=None,
            candidate_counts={"vector": 1, "fts": 1, "selected": 1},
            retrieval_config_version="hybrid-v1",
            query_class="fact",
            strategy_name="query-aware-fact",
        )


def test_run_retrieval_evaluation_persists_workspace_scoped_run():
    repository = _Repository()
    retrieval_service = _RetrievalService()
    service = EvaluationService(
        repository=repository,
        retrieval_service=retrieval_service,
        settings=SimpleNamespace(
            evaluation_dataset_path="tests/evaluation/datasets/golden_dataset.json",
            max_context_chunks=8,
            retrieval_sensitivity_ceiling=None,
        ),
    )
    workspace_id = uuid4()

    run_id = asyncio.run(
        service.run_retrieval_evaluation(workspace_id=workspace_id, model_profile="balanced")
    )

    assert run_id == repository.run_id
    assert repository.payload.workspace_id == workspace_id
    assert repository.payload.run_type == "retrieval"
    assert repository.payload.model_profile == "balanced"
    assert repository.payload.metrics["recall_at_5"] == 1.0
    assert retrieval_service.requests[0].question == "What is the remote work policy?"
    assert retrieval_service.requests[0].filters == {"department": "hr"}
    assert repository.payload.details["predictions"][0]["predicted_document_ids"] == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ]
