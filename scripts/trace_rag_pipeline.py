from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.container import AppContainer
from app.domain.entities.rag import Principal
from app.llm.grounded_answering import answer_grounded_question
from app.retrieval.retriever import (
    _apply_structural_boosts,
    _assemble_context,
    _classify_query,
    _deduplicate_candidates,
    _extract_query_features,
    _merge_candidates,
    _query_strategy,
    _rewrite_query,
    _should_rewrite,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trace the full internal RAG pipeline for one document and one question."
    )
    parser.add_argument("--document-id", required=True, help="Document UUID to trace.")
    parser.add_argument("--question", required=True, help="Question to ask against the document.")
    parser.add_argument("--workspace-id", help="Optional workspace UUID override.")
    parser.add_argument("--profile", default="balanced", help="Chat profile to use.")
    parser.add_argument("--top-k", type=int, default=None, help="Final selected source count.")
    parser.add_argument("--vector-limit", type=int, default=None, help="Vector candidate limit override.")
    parser.add_argument("--fts-limit", type=int, default=None, help="FTS candidate limit override.")
    parser.add_argument("--preview", type=int, default=240, help="Preview length for chunk text.")
    parser.add_argument("--json-output", help="Optional path to write the full trace as JSON.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    container = AppContainer(settings)

    document_meta = await _resolve_document(
        db=container.db,
        document_id=args.document_id,
        workspace_id=args.workspace_id,
    )
    workspace_id = UUID(str(document_meta["workspace_id"]))
    document_id = UUID(str(document_meta["id"]))
    principal = Principal(
        user_id=UUID(settings.dev_user_id),
        email=settings.dev_user_email,
        auth_method="api_key",
        role="owner",
    )

    stored = await _fetch_stored_document_state(
        db=container.db,
        document_id=document_id,
        preview=args.preview,
    )
    trace = await _trace_retrieval_and_answer(
        container=container,
        principal=principal,
        workspace_id=workspace_id,
        document_id=document_id,
        question=args.question,
        profile=args.profile,
        top_k=args.top_k or settings.max_context_chunks,
        vector_limit=args.vector_limit or settings.retrieval_vector_candidate_count,
        fts_limit=args.fts_limit or settings.retrieval_fts_candidate_count,
        preview=args.preview,
    )

    payload = {
        "document": document_meta,
        "stored_state": stored,
        "trace": trace,
    }

    _print_trace(payload, preview=args.preview)

    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print()
        print(f"JSON trace written to: {path}")


async def _resolve_document(*, db, document_id: str, workspace_id: str | None) -> dict[str, Any]:
    where = ["id = %s::uuid", "deleted_at is null"]
    params: list[Any] = [document_id]
    if workspace_id:
        where.append("workspace_id = %s::uuid")
        params.append(workspace_id)
    query = f"""
        select id, workspace_id, title, source_type, status, created_at
        from documents
        where {' and '.join(where)}
        limit 1
    """
    async with db.connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, params)
            row = await cursor.fetchone()
    if not row:
        raise SystemExit(f"Document not found: {document_id}")
    return _jsonify(dict(row))


async def _fetch_stored_document_state(*, db, document_id: UUID, preview: int) -> dict[str, Any]:
    async with db.connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                select order_index, block_type, heading_level, page_number, section_title,
                       subsection_title, section_path, parent_block_id, metadata, text
                from document_blocks
                where document_id = %s
                order by order_index
                """,
                (document_id,),
            )
            blocks = await cursor.fetchall()

            await cursor.execute(
                """
                select id, chunk_role, chunk_index, chunk_type, page_number, section_title,
                       subsection_title, section_path, parent_block_id, metadata, block_order_start,
                       block_order_end, token_count, content
                from document_chunks
                where document_id = %s
                order by
                    case chunk_role when 'parent' then 0 else 1 end,
                    block_order_start nulls last,
                    chunk_index asc
                """,
                (document_id,),
            )
            chunks = await cursor.fetchall()

    return {
        "block_count": len(blocks),
        "chunk_count": len(chunks),
        "blocks": [
            {
                **_jsonify(dict(row)),
                "text_preview": _preview(row["text"], preview),
            }
            for row in blocks
        ],
        "chunks": [
            {
                **_jsonify(dict(row)),
                "content_preview": _preview(row["content"], preview),
            }
            for row in chunks
        ],
    }


async def _trace_retrieval_and_answer(
    *,
    container: AppContainer,
    principal: Principal,
    workspace_id: UUID,
    document_id: UUID,
    question: str,
    profile: str,
    top_k: int,
    vector_limit: int,
    fts_limit: int,
    preview: int,
) -> dict[str, Any]:
    filters = {"document_ids": [str(document_id)]}
    query_features = _extract_query_features(question)
    query_class = _classify_query(question, query_features)
    strategy = _query_strategy(
        query_text=question,
        query_class=query_class,
        query_features=query_features,
        requested_top_k=top_k,
        settings=container.settings,
    )
    embedding_result = await container.model_router.embed_texts([question])
    query_embedding = embedding_result.vectors[0]

    vector_rows = await container.retrieval_repository.search_vector_candidates(
        workspace_id=workspace_id,
        user_id=principal.user_id,
        query_embedding=query_embedding,
        limit=vector_limit or strategy["vector_limit"],
        filters=filters,
        sensitivity_ceiling=container.settings.retrieval_sensitivity_ceiling,
    )
    fts_rows = await container.retrieval_repository.search_fts_candidates(
        workspace_id=workspace_id,
        user_id=principal.user_id,
        query_text=question,
        limit=fts_limit or strategy["fts_limit"],
        filters=filters,
        sensitivity_ceiling=container.settings.retrieval_sensitivity_ceiling,
    )

    merged = _merge_candidates(
        vector_rows,
        fts_rows,
        container.settings,
        vector_weight=strategy["vector_weight"],
        fts_weight=strategy["fts_weight"],
    )
    merged = _apply_structural_boosts(merged, question, query_features=query_features)
    rewrite_used = False
    rewritten_query = question

    if _should_rewrite(merged, container.settings, allow_rewrite=strategy["allow_rewrite"]):
        candidate_rewrite = _rewrite_query(question)
        if candidate_rewrite and candidate_rewrite != question:
            rewrite_used = True
            rewritten_query = candidate_rewrite
            rewritten_embedding = (await container.model_router.embed_texts([rewritten_query])).vectors[0]
            vector_rows = await container.retrieval_repository.search_vector_candidates(
                workspace_id=workspace_id,
                user_id=principal.user_id,
                query_embedding=rewritten_embedding,
                limit=vector_limit or strategy["vector_limit"],
                filters=filters,
                sensitivity_ceiling=container.settings.retrieval_sensitivity_ceiling,
            )
            fts_rows = await container.retrieval_repository.search_fts_candidates(
                workspace_id=workspace_id,
                user_id=principal.user_id,
                query_text=rewritten_query,
                limit=fts_limit or strategy["fts_limit"],
                filters=filters,
                sensitivity_ceiling=container.settings.retrieval_sensitivity_ceiling,
            )
            merged = _merge_candidates(
                vector_rows,
                fts_rows,
                container.settings,
                vector_weight=strategy["vector_weight"],
                fts_weight=strategy["fts_weight"],
            )
            merged = _apply_structural_boosts(merged, rewritten_query, query_features=query_features)

    reranked = await container.reranker.rerank(rewritten_query, list(merged))
    reranker_used = getattr(container.reranker, "model_name", None) is not None
    deduped = _deduplicate_candidates(
        list(reranked),
        container.settings.retrieval_dedup_similarity_threshold,
    )
    await container.retrieval_service._hydrate_parent_context(deduped)
    context = _assemble_context(
        deduped,
        requested_top_k=strategy["requested_top_k"],
        max_chunks_per_document=strategy["max_chunks_per_document"],
        context_token_budget=strategy["context_token_budget"],
        section_diversity_target=strategy["section_diversity_target"],
        support_sections_target=strategy["support_sections_target"],
        min_incremental_terms=strategy["min_incremental_terms"],
        prefer_diversity=strategy["prefer_diversity"],
        query_class=query_class,
    )
    container.security_policy.enforce_chat_sensitivity_policy(
        model_profile=profile,
        selected_sources=context.candidates,
    )
    answer_result = await answer_grounded_question(
        model_router=container.model_router,
        question=question,
        source_blocks=context.source_blocks,
        profile=profile,
        query_class=context.assembly_policy.get("query_class", "fact"),
        retrieval_metadata={
            "candidate_counts": {
                "vector": len(vector_rows),
                "fts": len(fts_rows),
                "selected": len(context.candidates),
            }
        },
    )

    return {
        "question": question,
        "profile": profile,
        "rewrite_used": rewrite_used,
        "rewritten_query": rewritten_query,
        "reranker_used": reranker_used,
        "summary": {
            "vector_candidate_count": len(vector_rows),
            "fts_candidate_count": len(fts_rows),
            "merged_candidate_count": len(merged),
            "reranked_candidate_count": len(list(reranked)),
            "deduped_candidate_count": len(deduped),
            "selected_source_count": len(context.candidates),
            "selected_sections": [_source_section_name(item) for item in context.candidates],
            "selected_pages": [item.page_number for item in context.candidates if item.page_number is not None],
        },
        "query_class": query_class,
        "query_features": query_features,
        "strategy_name": strategy["name"],
        "embedding": {
            "provider": embedding_result.provider,
            "model_name": embedding_result.model_name,
            "input_tokens": embedding_result.input_tokens,
            "estimated_cost_usd": embedding_result.estimated_cost_usd,
        },
        "vector_candidates": [_row_to_trace(row, preview=preview) for row in vector_rows],
        "fts_candidates": [_row_to_trace(row, preview=preview) for row in fts_rows],
        "merged_candidates": [_candidate_to_trace(item, preview=preview) for item in merged],
        "reranked_candidates": [_candidate_to_trace(item, preview=preview) for item in list(reranked)],
        "deduped_candidates": [_candidate_to_trace(item, preview=preview) for item in deduped],
        "selected_sources": [_candidate_to_trace(item, preview=preview) for item in context.candidates],
        "context": {
            "total_tokens": context.total_tokens,
            "dropped_reasons": context.dropped_reasons,
            "source_blocks": context.source_blocks,
            "assembly_policy": context.assembly_policy,
        },
        "answer": {
            "text": answer_result.answer,
            "provider": answer_result.provider,
            "model_name": answer_result.model_name,
            "input_tokens": answer_result.input_tokens,
            "output_tokens": answer_result.output_tokens,
            "estimated_cost_usd": answer_result.estimated_cost_usd,
            "prompt_family": answer_result.prompt_family,
            "verification_used": answer_result.verification_used,
            "verification_outcome": answer_result.verification_outcome,
            "completion_count": answer_result.completion_count,
            "planning": answer_result.planning,
            "verification": answer_result.verification,
        },
    }


def _row_to_trace(row: Any, *, preview: int) -> dict[str, Any]:
    payload = _jsonify(asdict(row))
    if "id" in payload and "chunk_id" not in payload:
        payload["chunk_id"] = payload["id"]
    payload["content_preview"] = _preview(row.content, preview)
    return payload


def _candidate_to_trace(candidate: Any, *, preview: int) -> dict[str, Any]:
    payload = _jsonify(asdict(candidate))
    payload["content_preview"] = _preview(candidate.content, preview)
    payload["parent_content_preview"] = _preview(candidate.parent_content, preview) if candidate.parent_content else None
    return payload


def _preview(value: str | None, length: int) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= length else collapsed[: length - 3] + "..."


def _jsonify(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonify(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _print_trace(payload: dict[str, Any], *, preview: int) -> None:
    document = payload["document"]
    stored = payload["stored_state"]
    trace = payload["trace"]

    print("=== DOCUMENT ===")
    print(f"title: {document['title']}")
    print(f"document_id: {document['id']}")
    print(f"workspace_id: {document['workspace_id']}")
    print(f"source_type: {document['source_type']}")
    print(f"status: {document['status']}")
    print()

    print("=== STORED BLOCKS ===")
    print(f"count: {stored['block_count']}")
    print(f"kind_counts: {_kind_counts(stored['blocks'], field='block_type')}")
    for block in stored["blocks"]:
        metadata = block.get("metadata") or {}
        print(
            f"- order={block['order_index']} type={block['block_type']} "
            f"page={block['page_number']} section={block['section_title']} "
            f"path={block['section_path']}"
        )
        print(
            f"  content_kind={metadata.get('content_kind')} "
            f"table_id={metadata.get('table_id')} equation_id={metadata.get('equation_id')} "
            f"algorithm_id={metadata.get('algorithm_id')} caption_label={metadata.get('caption_label')}"
        )
        print(f"  preview: {block['text_preview']}")
    print()

    print("=== STORED CHUNKS ===")
    print(f"count: {stored['chunk_count']}")
    print(f"kind_counts: {_kind_counts(stored['chunks'], metadata_key='content_kind', field='chunk_type')}")
    for chunk in stored["chunks"]:
        metadata = chunk.get("metadata") or {}
        print(
            f"- role={chunk['chunk_role']} idx={chunk['chunk_index']} "
            f"page={chunk['page_number']} type={chunk['chunk_type']} "
            f"section={chunk['section_title']} score_fields=tokens:{chunk['token_count']}"
        )
        print(
            f"  content_kind={metadata.get('content_kind')} "
            f"group={metadata.get('structure_group_id')} "
            f"caption_label={metadata.get('caption_label')} "
            f"equation_label={metadata.get('equation_label')} "
            f"algorithm_label={metadata.get('algorithm_label')}"
        )
        print(f"  preview: {chunk['content_preview']}")
    print()

    print("=== QUERY ===")
    print(f"question: {trace['question']}")
    print(f"profile: {trace['profile']}")
    print(f"query_class: {trace['query_class']}")
    print(f"strategy_name: {trace['strategy_name']}")
    print(f"query_features: {trace['query_features']}")
    print(f"rewrite_used: {trace['rewrite_used']}")
    if trace["rewrite_used"]:
        print(f"rewritten_query: {trace['rewritten_query']}")
    print(f"reranker_used: {trace['reranker_used']}")
    print(f"candidate_summary: {trace['summary']}")
    print()

    _print_candidate_section("VECTOR CANDIDATES", trace["vector_candidates"])
    _print_candidate_section("FTS CANDIDATES", trace["fts_candidates"])
    _print_candidate_section("MERGED CANDIDATES", trace["merged_candidates"])
    _print_candidate_section("RERANKED CANDIDATES", trace["reranked_candidates"])
    _print_candidate_section("DEDUPED CANDIDATES", trace["deduped_candidates"])
    _print_candidate_section("SELECTED SOURCES", trace["selected_sources"])

    print("=== CONTEXT BLOCKS SENT TO MODEL ===")
    print(f"total_tokens_estimate: {trace['context']['total_tokens']}")
    print(f"dropped_reasons: {trace['context']['dropped_reasons']}")
    print(f"assembly_policy: {trace['context']['assembly_policy']}")
    for index, block in enumerate(trace["context"]["source_blocks"], start=1):
        print(f"[context {index}]")
        print(_preview(block, max(preview * 3, preview)))
    print()

    answer = trace["answer"]
    print("=== FINAL ANSWER ===")
    print(f"provider: {answer['provider']}")
    print(f"model: {answer['model_name']}")
    print(f"input_tokens: {answer['input_tokens']}")
    print(f"output_tokens: {answer['output_tokens']}")
    print(f"estimated_cost_usd: {answer['estimated_cost_usd']}")
    print(f"prompt_family: {answer['prompt_family']}")
    print(f"verification_used: {answer['verification_used']}")
    print(f"verification_outcome: {answer['verification_outcome']}")
    if answer.get("planning") is not None:
        print(f"planning: {answer['planning']}")
    if answer.get("verification") is not None:
        print(f"verification: {answer['verification']}")
    print(answer["text"])


def _print_candidate_section(title: str, items: list[dict[str, Any]]) -> None:
    print(f"=== {title} ===")
    if not items:
        print("none")
        print()
        return
    for index, item in enumerate(items, start=1):
        chunk_id = item.get("chunk_id") or item.get("id")
        print(
            f"{index}. chunk_id={chunk_id} doc={item['document_id']} "
            f"page={item['page_number']} section={item['section_title']} "
            f"vector={item.get('vector_score')} fts={item.get('fts_score')} fused={item.get('fused_score')}"
        )
        print(f"   path={item.get('section_path')}")
        print(
            f"   content_kind={(item.get('metadata') or {}).get('content_kind')} "
            f"group={(item.get('metadata') or {}).get('structure_group_id')} "
            f"caption={(item.get('metadata') or {}).get('caption_label')} "
            f"equation={(item.get('metadata') or {}).get('equation_label')} "
            f"algorithm={(item.get('metadata') or {}).get('algorithm_label')}"
        )
        print(f"   preview={item.get('parent_content_preview') or item.get('content_preview')}")
    print()


def _source_section_name(candidate: Any) -> str:
    if candidate.section_title:
        return candidate.section_title
    if candidate.subsection_title:
        return candidate.subsection_title
    if candidate.section_path:
        return candidate.section_path[-1]
    return candidate.title


def _kind_counts(items: list[dict[str, Any]], *, metadata_key: str = "content_kind", field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        metadata = item.get("metadata") or {}
        key = metadata.get(metadata_key) or item.get(field) or "unknown"
        counts[str(key)] = counts.get(str(key), 0) + 1
    return counts


if __name__ == "__main__":
    asyncio.run(main())
