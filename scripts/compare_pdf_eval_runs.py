from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two PDF evaluation runs and their score sheets.")
    parser.add_argument("--baseline-run", required=True, help="Baseline run JSON path.")
    parser.add_argument("--candidate-run", required=True, help="Candidate run JSON path.")
    parser.add_argument("--baseline-scores", required=True, help="Baseline scoring CSV path.")
    parser.add_argument("--candidate-scores", required=True, help="Candidate scoring CSV path.")
    parser.add_argument("--json-output", help="Optional path to write the comparison as JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    baseline_run = _read_json(Path(args.baseline_run))
    candidate_run = _read_json(Path(args.candidate_run))
    baseline_scores = _read_csv(Path(args.baseline_scores))
    candidate_scores = _read_csv(Path(args.candidate_scores))

    payload = {
        "baseline_run_id": baseline_run.get("run_id"),
        "candidate_run_id": candidate_run.get("run_id"),
        "overall": {
            "retrieval": {
                "baseline": _retrieval_summary(baseline_run),
                "candidate": _retrieval_summary(candidate_run),
            },
            "scored": {
                "baseline": _score_summary(baseline_scores),
                "candidate": _score_summary(candidate_scores),
            },
        },
        "by_query_class": _query_class_summary(baseline_run, candidate_run),
        "question_deltas": _question_deltas(baseline_scores, candidate_scores),
    }

    _print_summary(payload)
    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print()
        print(f"JSON comparison written to: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _retrieval_summary(run_payload: dict[str, Any]) -> dict[str, float]:
    questions = run_payload.get("questions", [])
    top1 = [item.get("retrieval", {}).get("top1_hit") for item in questions if item.get("retrieval", {}).get("top1_hit") is not None]
    top3 = [item.get("retrieval", {}).get("top3_hit") for item in questions if item.get("retrieval", {}).get("top3_hit") is not None]
    return {
        "top1_hit_rate": _truth_rate(top1),
        "top3_hit_rate": _truth_rate(top3),
        "avg_latency_ms": _average([item.get("latency_ms", 0) for item in questions]),
    }


def _score_summary(rows: list[dict[str, str]]) -> dict[str, float]:
    return {
        "avg_correctness": _average_numeric_column(rows, "correctness_score"),
        "avg_grounding": _average_numeric_column(rows, "grounding_score"),
        "avg_completeness": _average_numeric_column(rows, "completeness_score"),
        "avg_citation_quality": _average_numeric_column(rows, "citation_quality_score"),
        "hallucination_rate": _hallucination_rate(rows),
    }


def _query_class_summary(
    baseline_run: dict[str, Any],
    candidate_run: dict[str, Any],
) -> dict[str, dict[str, float]]:
    baseline_by_class = defaultdict(list)
    candidate_by_class = defaultdict(list)
    for item in baseline_run.get("questions", []):
        baseline_by_class[item.get("metadata", {}).get("query_class", "unknown")].append(item)
    for item in candidate_run.get("questions", []):
        candidate_by_class[item.get("metadata", {}).get("query_class", "unknown")].append(item)

    payload: dict[str, dict[str, float]] = {}
    for key in sorted(set(baseline_by_class) | set(candidate_by_class)):
        payload[key] = {
            "baseline_top1_hit_rate": _truth_rate([row.get("retrieval", {}).get("top1_hit") for row in baseline_by_class[key] if row.get("retrieval", {}).get("top1_hit") is not None]),
            "candidate_top1_hit_rate": _truth_rate([row.get("retrieval", {}).get("top1_hit") for row in candidate_by_class[key] if row.get("retrieval", {}).get("top1_hit") is not None]),
            "baseline_top3_hit_rate": _truth_rate([row.get("retrieval", {}).get("top3_hit") for row in baseline_by_class[key] if row.get("retrieval", {}).get("top3_hit") is not None]),
            "candidate_top3_hit_rate": _truth_rate([row.get("retrieval", {}).get("top3_hit") for row in candidate_by_class[key] if row.get("retrieval", {}).get("top3_hit") is not None]),
        }
    return payload


def _question_deltas(baseline_rows: list[dict[str, str]], candidate_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    baseline_map = {row["question_id"]: row for row in baseline_rows}
    candidate_map = {row["question_id"]: row for row in candidate_rows}
    deltas: list[dict[str, Any]] = []
    for question_id in sorted(set(baseline_map) & set(candidate_map)):
        baseline = baseline_map[question_id]
        candidate = candidate_map[question_id]
        deltas.append(
            {
                "question_id": question_id,
                "baseline_correctness": _maybe_float(baseline.get("correctness_score")),
                "candidate_correctness": _maybe_float(candidate.get("correctness_score")),
                "baseline_grounding": _maybe_float(baseline.get("grounding_score")),
                "candidate_grounding": _maybe_float(candidate.get("grounding_score")),
                "baseline_completeness": _maybe_float(baseline.get("completeness_score")),
                "candidate_completeness": _maybe_float(candidate.get("completeness_score")),
            }
        )
    return deltas


def _average(values: list[Any]) -> float:
    numbers = [float(value) for value in values if value not in ("", None)]
    return round(sum(numbers) / len(numbers), 4) if numbers else 0.0


def _average_numeric_column(rows: list[dict[str, str]], column: str) -> float:
    return _average([_maybe_float(row.get(column)) for row in rows if _maybe_float(row.get(column)) is not None])


def _hallucination_rate(rows: list[dict[str, str]]) -> float:
    values = [row.get("hallucination", "").strip().lower() for row in rows if row.get("hallucination", "").strip()]
    if not values:
        return 0.0
    return round(sum(1 for value in values if value == "yes") / len(values), 4)


def _truth_rate(values: list[Any]) -> float:
    normalized = [value for value in values if value is not None]
    if not normalized:
        return 0.0
    return round(sum(1 for value in normalized if bool(value)) / len(normalized), 4)


def _maybe_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _print_summary(payload: dict[str, Any]) -> None:
    print("=== RUN COMPARISON ===")
    print(f"baseline: {payload['baseline_run_id']}")
    print(f"candidate: {payload['candidate_run_id']}")
    print()
    print("retrieval:")
    print(payload["overall"]["retrieval"])
    print("scored:")
    print(payload["overall"]["scored"])
    print("by_query_class:")
    print(payload["by_query_class"])


if __name__ == "__main__":
    main()
