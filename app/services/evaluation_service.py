from __future__ import annotations

from uuid import UUID

from app.core.config import Settings
from app.evaluation.datasets import GoldenDatasetRepository
from app.evaluation.runner import EvaluationRunner
from app.storage.repositories.rag import RagRepository


class EvaluationService:
    def __init__(self, *, repository: RagRepository, settings: Settings):
        self.repository = repository
        self.dataset_repository = GoldenDatasetRepository(settings.evaluation_dataset_path)
        self.runner = EvaluationRunner()

    async def run_retrieval_evaluation(self, *, tenant_id: UUID, model_profile: str = "balanced") -> UUID:
        dataset = self.dataset_repository.load()
        result = self.runner.run_retrieval_evaluation(dataset)
        return await self.repository.create_evaluation_run(
            tenant_id=tenant_id,
            run_type="retrieval",
            model_profile=model_profile,
            metrics=result.metrics,
            details=result.details,
        )
