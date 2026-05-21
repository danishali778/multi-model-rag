from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.container import AppContainer
from app.domain.entities.rag import Principal, RetrievalRequest
from app.llm.grounded_answering import answer_grounded_question


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a PDF RAG evaluation dataset against the real retrieval/chat stack."
    )
    parser.add_argument(
        "--dataset",
        default="tests/evaluation/datasets/complex_eval_report_eval.json",
        help="Path to the evaluation dataset JSON.",
    )
    parser.add_argument(
        "--run-output",
        default="tests/evaluation/runs/complex_eval_report_run_001.json",
        help="Path to write the raw run JSON.",
    )
    parser.add_argument(
        "--scores-output",
        default="tests/evaluation/results/complex_eval_report_run_001_scores.csv",
        help="Path to write the scoring CSV.",
    )
    parser.add_argument(
        "--document-id",
        help="Exact document UUID to evaluate against. If omitted, the runner resolves by title.",
    )
    parser.add_argument(
        "--workspace-id",
        help="Optional workspace UUID to narrow document resolution.",
    )
    parser.add_argument(
        "--title",
        help="Document title override. Defaults to the dataset document_name.",
    )
    parser.add_argument(
        "--profile",
        default="balanced",
        help="Chat profile to use for answer generation.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Requested top-k retrieval depth. Defaults to settings.max_context_chunks.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional question limit for a partial run.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first question error instead of continuing and recording the failure.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    run_output_path = Path(args.run_output)
    scores_output_path = Path(args.scores_output)

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    settings = get_settings()
    container = AppContainer(settings)

    document = await _resolve_document(
        db=container.db,
        document_id=args.document_id,
        workspace_id=args.workspace_id,
        title=args.title or dataset["document_name"],
    )

    principal = Principal(
        user_id=UUID(settings.dev_user_id),
        email=settings.dev_user_email,
        auth_method="api_key",
        role="owner",
    )

    questions = dataset["questions"][: args.limit] if args.limit else dataset["questions"]
    run_payload = _build_run_payload(
        dataset=dataset,
        dataset_path=dataset_path,
        run_output_path=run_output_path,
        document=document,
        profile=args.profile,
        top_k=args.top_k or settings.max_context_chunks,
        question_count=len(questions),
    )

    for index, question in enumerate(questions, start=1):
        print(f"[{index}/{len(questions)}] {question['id']}: {question['question']}")
        try:
            result = await _run_question(
                container=container,
                principal=principal,
                workspace_id=document["workspace_id"],
                document_id=document["id"],
                question=question,
                profile=args.profile,
                requested_top_k=args.top_k or settings.max_context_chunks,
            )
        except Exception as exc:
            if args.fail_fast:
                raise
            result = _error_result(question, str(exc))
        run_payload["questions"].append(result)
        if not run_payload["model"]:
            run_payload["model"] = result.get("metadata", {}).get("model", "")
        _write_json(run_output_path, run_payload)

    _write_scores_csv(scores_output_path, dataset, run_payload)

    print()
    print(f"Run output written to: {run_output_path}")
    print(f"Scoring CSV written to: {scores_output_path}")


async def _resolve_document(
    *,
    db,
    document_id: str | None,
    workspace_id: str | None,
    title: str,
) -> dict[str, Any]:
    where = ["deleted_at is null"]
    params: list[Any] = []

    if document_id:
        where.append("id = %s::uuid")
        params.append(document_id)
    else:
        where.append("title = %s")
        params.append(title)

    if workspace_id:
        where.append("workspace_id = %s::uuid")
        params.append(workspace_id)

    query = f"""
        select id, workspace_id, title, created_at
        from documents
        where {' and '.join(where)}
        order by created_at desc
        limit 1
    """

    async with db.connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, params)
            row = await cursor.fetchone()

    if not row:
        if document_id:
            raise SystemExit(f"Document not found for document_id={document_id}")
        raise SystemExit(f"Document not found for title={title!r}")

    return dict(row)


def _build_run_payload(
    *,
    dataset: dict[str, Any],
    dataset_path: Path,
    run_output_path: Path,
    document: dict[str, Any],
    profile: str,
    top_k: int,
    question_count: int,
) -> dict[str, Any]:
    return {
        "run_id": run_output_path.stem,
        "document_id": dataset["document_id"],
        "document_name": dataset["document_name"],
        "dataset_file": str(dataset_path),
        "source_file": dataset["source_file"],
        "resolved_document": {
            "id": str(document["id"]),
            "workspace_id": str(document["workspace_id"]),
            "title": document["title"],
        },
        "timestamp": _utc_timestamp(),
        "profile": profile,
        "model": "",
        "retrieval_top_k": top_k,
        "notes": f"Auto-generated run for {question_count} questions.",
        "questions": [],
    }


async def _run_question(
    *,
    container: AppContainer,
    principal: Principal,
    workspace_id: UUID,
    document_id: UUID,
    question: dict[str, Any],
    profile: str,
    requested_top_k: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    decision = await container.retrieval_service.retrieve(
        RetrievalRequest(
            workspace_id=workspace_id,
            user_id=principal.user_id,
            question=question["question"],
            filters={"document_ids": [str(document_id)]},
            requested_top_k=requested_top_k,
            model_profile=profile,
            sensitivity_ceiling=getattr(container.settings, "retrieval_sensitivity_ceiling", None),
        )
    )
    container.security_policy.enforce_chat_sensitivity_policy(
        model_profile=profile,
        selected_sources=decision.selected_sources,
    )

    answer_result = await answer_grounded_question(
        model_router=container.model_router,
        question=question["question"],
        source_blocks=decision.context.source_blocks,
        profile=profile,
        query_class=decision.query_class,
        retrieval_metadata={
            "candidate_counts": decision.candidate_counts,
            "strategy_name": decision.strategy_name,
        },
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    retrieved_sections = [_source_section_name(source) for source in decision.selected_sources]
    retrieved_pages = [source.page_number for source in decision.selected_sources if source.page_number is not None]
    retrieved_chunk_ids = [str(source.chunk_id) for source in decision.selected_sources]
    citations = [
        {
            "source_id": index,
            "title": source.title,
            "section": _source_section_name(source),
            "page": source.page_number,
            "chunk_id": str(source.chunk_id),
            "score": source.fused_score,
            "snippet": source.content,
        }
        for index, source in enumerate(decision.selected_sources, start=1)
    ]

    return {
        "question_id": question["id"],
        "question": question["question"],
        "should_be_answerable": question["should_be_answerable"],
        "retrieval": {
            "top1_hit": _top_hit(question, decision.selected_sources[:1]),
            "top3_hit": _top_hit(question, decision.selected_sources[:3]),
            "retrieved_sections": retrieved_sections,
            "retrieved_pages": retrieved_pages,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieval_notes": "",
        },
        "answer": answer_result.answer,
        "citations": citations,
        "latency_ms": latency_ms,
        "usage": {
            "input_tokens": answer_result.input_tokens,
            "output_tokens": answer_result.output_tokens,
            "total_tokens": answer_result.input_tokens + answer_result.output_tokens,
            "estimated_cost_usd": answer_result.estimated_cost_usd,
        },
        "metadata": {
            "answerable_behavior": "",
            "retrieval_mode": decision.retrieval_mode,
            "rewrite_used": decision.rewrite_used,
            "reranker_used": decision.reranker_used,
            "candidate_counts": decision.candidate_counts,
            "no_source_reason": decision.no_source_reason,
            "model": f"{answer_result.provider}:{answer_result.model_name}",
            "query_class": decision.query_class,
            "strategy_name": decision.strategy_name,
            "rewritten_query": decision.rewritten_query,
            "prompt_family": answer_result.prompt_family,
            "planning": answer_result.planning,
            "verification_used": answer_result.verification_used,
            "verification_outcome": answer_result.verification_outcome,
            "verification": answer_result.verification,
        },
    }


def _error_result(question: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "question_id": question["id"],
        "question": question["question"],
        "should_be_answerable": question["should_be_answerable"],
        "retrieval": {
            "top1_hit": None,
            "top3_hit": None,
            "retrieved_sections": [],
            "retrieved_pages": [],
            "retrieved_chunk_ids": [],
            "retrieval_notes": "",
        },
        "answer": "",
        "citations": [],
        "latency_ms": 0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        },
        "metadata": {
            "answerable_behavior": "",
            "error": error,
            "query_class": "",
            "strategy_name": "",
        },
    }


def _top_hit(question: dict[str, Any], sources: list[Any]) -> bool | None:
    if not sources:
        return False
    expected_sections = {value.lower() for value in question.get("must_cite_sections", [])}
    expected_pages = set(question.get("expected_pages", []))
    if not expected_sections and not expected_pages:
        return None

    for source in sources:
        section = _source_section_name(source).lower()
        if expected_sections and section in expected_sections:
            return True
        if expected_pages and source.page_number in expected_pages:
            return True
    return False


def _source_section_name(source: Any) -> str:
    if source.section_title:
        return source.section_title
    if source.subsection_title:
        return source.subsection_title
    if source.section_path:
        return source.section_path[-1]
    return source.title


def _write_scores_csv(
    path: Path,
    dataset: dict[str, Any],
    run_payload: dict[str, Any],
) -> None:
    dataset_questions = {item["id"]: item for item in dataset["questions"]}
    run_questions = {item["question_id"]: item for item in run_payload["questions"]}
    fieldnames = [
        "run_id",
        "question_id",
        "category",
        "difficulty",
        "question",
        "should_be_answerable",
        "expected_facts",
        "retrieved_sections",
        "retrieved_pages",
        "retrieved_chunk_ids",
        "top1_hit",
        "top3_hit",
        "query_class",
        "strategy_name",
        "answer",
        "citations",
        "correctness_score",
        "grounding_score",
        "completeness_score",
        "citation_quality_score",
        "hallucination",
        "answerable_behavior",
        "latency_ms",
        "reviewer",
        "notes",
    ]

    rows: list[dict[str, Any]] = []
    for item in dataset["questions"]:
        run = run_questions.get(item["id"], {})
        retrieval = run.get("retrieval", {})
        citations = run.get("citations", [])
        rows.append(
            {
                "run_id": run_payload["run_id"],
                "question_id": item["id"],
                "category": item["category"],
                "difficulty": item["difficulty"],
                "question": item["question"],
                "should_be_answerable": item["should_be_answerable"],
                "expected_facts": " | ".join(item.get("expected_facts", [])),
                "retrieved_sections": " | ".join(retrieval.get("retrieved_sections", [])),
                "retrieved_pages": " | ".join(str(page) for page in retrieval.get("retrieved_pages", [])),
                "retrieved_chunk_ids": " | ".join(retrieval.get("retrieved_chunk_ids", [])),
                "top1_hit": retrieval.get("top1_hit", ""),
                "top3_hit": retrieval.get("top3_hit", ""),
                "query_class": run.get("metadata", {}).get("query_class", ""),
                "strategy_name": run.get("metadata", {}).get("strategy_name", ""),
                "answer": run.get("answer", ""),
                "citations": " | ".join(_format_citation(citation) for citation in citations),
                "correctness_score": "",
                "grounding_score": "",
                "completeness_score": "",
                "citation_quality_score": "",
                "hallucination": "",
                "answerable_behavior": run.get("metadata", {}).get("answerable_behavior", ""),
                "latency_ms": run.get("latency_ms", ""),
                "reviewer": "",
                "notes": run.get("metadata", {}).get("error", ""),
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _format_citation(citation: dict[str, Any]) -> str:
    section = citation.get("section") or citation.get("title") or "unknown"
    page = citation.get("page")
    chunk_id = citation.get("chunk_id")
    bits = [section]
    if page is not None:
        bits.append(f"p.{page}")
    if chunk_id:
        bits.append(chunk_id)
    return " ".join(bits)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _utc_timestamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    asyncio.run(main())
