from app.evaluation.datasets import GoldenDatasetRepository
from app.evaluation.metrics import EvaluationMetrics
from app.evaluation.runner import EvaluationRunner, PredictionSample


def test_golden_dataset_loader_reads_fixture():
    repo = GoldenDatasetRepository("tests/evaluation/datasets/golden_dataset.json")
    items = repo.load()
    assert len(items) == 1
    assert items[0].question == "What is the remote work policy?"


def test_evaluation_runner_returns_metrics():
    repo = GoldenDatasetRepository("tests/evaluation/datasets/golden_dataset.json")
    items = repo.load()
    runner = EvaluationRunner()
    result = runner.run_retrieval_evaluation(
        items,
        [
            PredictionSample(
                document_ids=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                source_texts=["Remote work is allowed three days per week with manager approval."],
            )
        ],
    )
    assert result.metrics["unauthorized_source_rate"] == 0.0
    assert result.metrics["recall_at_5"] == 1.0


def test_citation_correctness_metric():
    assert EvaluationMetrics.citation_correctness("Answer with [source:1]", 1) == 1.0
    assert EvaluationMetrics.citation_correctness("Answer without source", 1) == 0.0


def test_generation_evaluation_groundedness():
    runner = EvaluationRunner()
    result = runner.run_generation_evaluation(
        [],
        [PredictionSample(document_ids=["doc-1"], source_texts=["remote work allowed"], answer="Remote work allowed [source:1]")],
    )
    assert result.metrics["citation_correctness"] == 1.0
