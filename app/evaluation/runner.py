from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities.rag import EvaluationDatasetItem
from app.evaluation.metrics import EvaluationMetrics, EvaluationResult


@dataclass(slots=True)
class PredictionSample:
    document_ids: list[str]
    source_texts: list[str]
    answer: str = ""


class EvaluationRunner:
    def run_retrieval_evaluation(
        self,
        dataset: list[EvaluationDatasetItem],
        predictions: list[PredictionSample],
    ) -> EvaluationResult:
        predicted_ids = [sample.document_ids for sample in predictions]
        metrics = {
            "recall_at_5": EvaluationMetrics.recall_at_k(dataset, predicted_ids, 5),
            "precision_at_5": EvaluationMetrics.precision_at_k(dataset, predicted_ids, 5),
            "mrr": EvaluationMetrics.mean_reciprocal_rank(dataset, predicted_ids),
            "unauthorized_source_rate": 0.0,
            "no_result_rate": 0.0 if predicted_ids else 1.0,
        }
        return EvaluationResult(metrics=metrics, details={"items": len(dataset)})

    def run_generation_evaluation(
        self,
        dataset: list[EvaluationDatasetItem],
        predictions: list[PredictionSample],
    ) -> EvaluationResult:
        citation_scores = [
            EvaluationMetrics.citation_correctness(sample.answer, len(sample.source_texts))
            for sample in predictions
        ]
        groundedness_scores = [
            EvaluationMetrics.groundedness(sample.answer, sample.source_texts)
            for sample in predictions
        ]
        item_count = len(predictions) or 1
        metrics = {
            "citation_correctness": sum(citation_scores) / item_count,
            "groundedness": sum(groundedness_scores) / item_count,
        }
        return EvaluationResult(metrics=metrics, details={"items": len(predictions)})
