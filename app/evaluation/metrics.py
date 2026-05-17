from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities.rag import EvaluationDatasetItem


@dataclass(slots=True)
class EvaluationResult:
    metrics: dict[str, float]
    details: dict


class EvaluationMetrics:
    @staticmethod
    def recall_at_k(dataset: list[EvaluationDatasetItem], predictions: list[list[str]], k: int) -> float:
        if not dataset:
            return 1.0
        scores: list[float] = []
        for item, predicted in zip(dataset, predictions, strict=False):
            required = set(item.required_document_ids)
            if not required:
                scores.append(1.0)
                continue
            hits = len(required.intersection(predicted[:k]))
            scores.append(hits / len(required))
        return sum(scores) / len(scores)

    @staticmethod
    def precision_at_k(dataset: list[EvaluationDatasetItem], predictions: list[list[str]], k: int) -> float:
        if not dataset:
            return 1.0
        scores: list[float] = []
        for item, predicted in zip(dataset, predictions, strict=False):
            window = predicted[:k]
            if not window:
                scores.append(0.0)
                continue
            required = set(item.required_document_ids)
            hits = len(required.intersection(window))
            scores.append(hits / len(window))
        return sum(scores) / len(scores)

    @staticmethod
    def mean_reciprocal_rank(dataset: list[EvaluationDatasetItem], predictions: list[list[str]]) -> float:
        if not dataset:
            return 1.0
        scores: list[float] = []
        for item, predicted in zip(dataset, predictions, strict=False):
            required = set(item.required_document_ids)
            reciprocal = 0.0
            for index, candidate in enumerate(predicted, start=1):
                if candidate in required:
                    reciprocal = 1 / index
                    break
            scores.append(reciprocal)
        return sum(scores) / len(scores)

    @staticmethod
    def citation_correctness(answer: str, source_count: int) -> float:
        if source_count == 0:
            return 1.0 if "[source:" not in answer else 0.0
        return 1.0 if any(f"[source:{index}]" in answer for index in range(1, source_count + 1)) else 0.0

    @staticmethod
    def groundedness(answer: str, source_texts: list[str]) -> float:
        if not source_texts:
            return 1.0 if "No accessible sources" in answer else 0.0
        answer_terms = {item.lower() for item in answer.split() if len(item) > 3}
        source_terms = {item.lower() for source in source_texts for item in source.split() if len(item) > 3}
        if not answer_terms:
            return 0.0
        overlap = len(answer_terms.intersection(source_terms))
        return overlap / len(answer_terms)
