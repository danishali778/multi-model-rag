from __future__ import annotations

from uuid import UUID

from app.core.config import Settings
from app.domain.entities.rag import RetrievalRequest
from app.evaluation.datasets import GoldenDatasetRepository
from app.evaluation.runner import EvaluationRunner, PredictionSample
from app.storage.models.evaluation import EvaluationRunCreateInput


class EvaluationService:
    def __init__(self, *, repository, retrieval_service, settings: Settings):
        self.repository = repository
        self.retrieval_service = retrieval_service
        self.dataset_repository = GoldenDatasetRepository(settings.evaluation_dataset_path)
        self.settings = settings
        self.runner = EvaluationRunner()

    async def run_retrieval_evaluation(self, *, workspace_id: UUID, model_profile: str = "balanced") -> UUID:
        dataset = self.dataset_repository.load()
        predictions: list[PredictionSample] = []
        prediction_details: list[dict[str, object]] = []
        for item in dataset:
            item_workspace_id = UUID(item.workspace_id) if item.workspace_id else workspace_id
            decision = await self.retrieval_service.retrieve(
                RetrievalRequest(
                    workspace_id=item_workspace_id,
                    user_id=UUID(item.user_id),
                    question=item.question,
                    filters=item.filters,
                    requested_top_k=getattr(self.settings, "max_context_chunks", 8),
                    model_profile=model_profile,
                    sensitivity_ceiling=getattr(self.settings, "retrieval_sensitivity_ceiling", None),
                )
            )
            predictions.append(
                PredictionSample(
                    document_ids=[str(candidate.document_id) for candidate in decision.selected_sources],
                    source_texts=[candidate.parent_content or candidate.content for candidate in decision.selected_sources],
                )
            )
            prediction_details.append(
                {
                    "question": item.question,
                    "expected_document_ids": list(item.required_document_ids),
                    "predicted_document_ids": [str(candidate.document_id) for candidate in decision.selected_sources],
                    "predicted_chunk_ids": [str(candidate.chunk_id) for candidate in decision.selected_sources],
                    "query_class": decision.query_class,
                    "strategy_name": decision.strategy_name,
                    "candidate_counts": dict(decision.candidate_counts),
                    "rewrite_used": decision.rewrite_used,
                    "reranker_used": decision.reranker_used,
                    "no_source_reason": decision.no_source_reason,
                    "workspace_id": str(item_workspace_id),
                    "user_id": item.user_id,
                }
            )
        result = self.runner.run_retrieval_evaluation(dataset, predictions)
        return await self.repository.create_evaluation_run(
            EvaluationRunCreateInput(
                workspace_id=workspace_id,
                run_type="retrieval",
                model_profile=model_profile,
                metrics=result.metrics,
                details={**result.details, "predictions": prediction_details},
            )
        )
