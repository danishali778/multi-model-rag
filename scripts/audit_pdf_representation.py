from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.storage.db.session import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit structural fidelity of a stored PDF representation."
    )
    parser.add_argument("--document-id", required=True, help="Exact document UUID to audit.")
    parser.add_argument(
        "--preview",
        type=int,
        default=180,
        help="Preview length for suspicious samples.",
    )
    parser.add_argument(
        "--json-output",
        help="Optional path to write the full audit as JSON.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    db = Database(get_settings())

    async with db.connection() as conn:
        async with conn.cursor() as cursor:
            document = await _fetch_document(cursor, args.document_id)
            if not document:
                raise SystemExit(f"Document not found: {args.document_id}")
            blocks = await _fetch_blocks(cursor, args.document_id)
            chunks = await _fetch_chunks(cursor, args.document_id)

    audit = build_representation_audit(document, blocks, chunks, preview=args.preview)
    _print_audit(audit)

    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_jsonify(audit), indent=2), encoding="utf-8")
        print()
        print(f"JSON audit written to: {path}")


async def _fetch_document(cursor: Any, document_id: str) -> dict[str, Any] | None:
    await cursor.execute(
        """
        select id, workspace_id, title, source_type, status, metadata, created_at
        from documents
        where id = %s::uuid and deleted_at is null
        limit 1
        """,
        (document_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _fetch_blocks(cursor: Any, document_id: str) -> list[dict[str, Any]]:
    await cursor.execute(
        """
        select
            order_index,
            block_type,
            heading_level,
            page_number,
            section_title,
            subsection_title,
            section_path,
            parent_block_id,
            metadata,
            text
        from document_blocks
        where document_id = %s::uuid
        order by order_index
        """,
        (document_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def _fetch_chunks(cursor: Any, document_id: str) -> list[dict[str, Any]]:
    await cursor.execute(
        """
        select
            id,
            chunk_role,
            chunk_index,
            chunk_type,
            page_number,
            section_title,
            subsection_title,
            section_path,
            parent_block_id,
            block_order_start,
            block_order_end,
            token_count,
            metadata,
            content
        from document_chunks
        where document_id = %s::uuid
        order by
            case chunk_role when 'parent' then 0 else 1 end,
            block_order_start nulls last,
            chunk_index asc
        """,
        (document_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


def build_representation_audit(
    document: dict[str, Any],
    blocks: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    *,
    preview: int,
) -> dict[str, Any]:
    parser_diagnostics = ((document.get("metadata") or {}).get("parser_diagnostics") or {})
    block_kind_counts = _count_kinds(blocks, fallback_field="block_type")
    chunk_kind_counts = _count_kinds(chunks, fallback_field="chunk_type")
    front_matter_blocks = [
        block for block in blocks if (block.get("metadata") or {}).get("content_kind") == "front_matter"
    ]
    excluded_from_chunking_count = sum(
        1 for block in blocks if (block.get("metadata") or {}).get("exclude_from_chunking")
    )
    abstract_heading_present = any(
        block["block_type"] == "heading" and str(block.get("text") or "").strip() == "Abstract"
        for block in blocks
    )
    title_emitted_as_heading = bool(
        document.get("title")
        and any(
            block["block_type"] == "heading"
            and str(block.get("text") or "").strip() == str(document.get("title") or "").strip()
            for block in blocks
        )
    )
    front_matter_leakage = [
        block
        for block in blocks
        if _looks_like_front_matter_leakage(block)
    ]
    abstract_noise = [
        block
        for block in blocks
        if _looks_like_abstract_noise(block)
    ]

    top_level_headings = [
        block["text"]
        for block in blocks
        if block["block_type"] == "heading" and (block.get("heading_level") == 1 or len(block.get("section_path") or []) == 1)
    ]
    suspicious_headings = [
        {
            "text": block["text"],
            "page_number": block["page_number"],
            "section_path": block.get("section_path") or [],
        }
        for block in blocks
        if block["block_type"] == "heading" and _is_suspicious_heading_block(block)
    ]

    front_matter_noise = [
        {
            "kind": block["block_type"],
            "page_number": block["page_number"],
            "text_preview": _preview(block["text"], preview),
        }
        for block in blocks
        if _is_front_matter_noise(block)
    ]

    table_stats = _table_coverage_stats(blocks, chunks, preview=preview)
    equation_stats = _equation_coverage_stats(blocks, chunks)
    figure_stats = _figure_caption_stats(blocks)
    algorithm_stats = _algorithm_stats(blocks, chunks)

    warnings = []
    if front_matter_noise:
        warnings.append(f"front_matter_noise:{len(front_matter_noise)}")
    if front_matter_leakage:
        warnings.append(f"front_matter_leakage:{len(front_matter_leakage)}")
    if abstract_noise:
        warnings.append(f"abstract_noise:{len(abstract_noise)}")
    if table_stats["captions_without_rows"] > 0:
        warnings.append(f"tables_without_rows:{table_stats['captions_without_rows']}")
    if table_stats["captions_without_rows"] >= table_stats["caption_count"] * 0.5 and table_stats["caption_count"] > 0:
        warnings.append("table_coverage_weak")
    if equation_stats["equation_count"] > 0 and equation_stats["equation_explanation_count"] == 0:
        warnings.append("equations_without_explanations")
    if suspicious_headings:
        warnings.append(f"suspicious_headings:{len(suspicious_headings)}")

    return {
        "document": _jsonify(document),
        "summary": {
            "block_count": len(blocks),
            "chunk_count": len(chunks),
            "block_kind_counts": block_kind_counts,
            "chunk_kind_counts": chunk_kind_counts,
            "top_level_headings": top_level_headings[:20],
            "front_matter_block_count": len(front_matter_blocks),
            "excluded_from_chunking_count": excluded_from_chunking_count,
            "front_matter_leakage_count": len(front_matter_leakage),
            "abstract_heading_present": abstract_heading_present,
            "abstract_non_abstract_noise_count": len(abstract_noise),
            "title_emitted_as_heading": title_emitted_as_heading,
            "page_artifact_suppressed_count": int(parser_diagnostics.get("page_artifact_suppressed_count", 0)),
            "decimal_subsection_heading_count": int(parser_diagnostics.get("decimal_subsection_heading_count", 0)),
            "merged_equation_fragment_count": int(parser_diagnostics.get("merged_equation_fragment_count", 0)),
            "equation_fragment_orphan_count": int(parser_diagnostics.get("equation_fragment_orphan_count", 0)),
            "multi_page_table_header_reuse_count": int(parser_diagnostics.get("multi_page_table_header_reuse_count", 0)),
            "warning_flags": warnings,
        },
        "front_matter": {
            "noise_count": len(front_matter_noise),
            "block_count": len(front_matter_blocks),
            "samples": front_matter_noise[:12],
            "leakage_samples": [
                {
                    "page_number": block.get("page_number"),
                    "text_preview": _preview(block.get("text"), preview),
                }
                for block in front_matter_leakage[:12]
            ],
        },
        "abstract": {
            "noise_count": len(abstract_noise),
            "samples": [
                {
                    "page_number": block.get("page_number"),
                    "text_preview": _preview(block.get("text"), preview),
                }
                for block in abstract_noise[:12]
            ],
        },
        "headings": {
            "top_level_count": len(top_level_headings),
            "suspicious_count": len(suspicious_headings),
            "suspicious_samples": suspicious_headings[:20],
        },
        "tables": table_stats,
        "equations": equation_stats,
        "figures": figure_stats,
        "algorithms": algorithm_stats,
    }


def _count_kinds(rows: list[dict[str, Any]], *, fallback_field: str) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        metadata = row.get("metadata") or {}
        kind = metadata.get("content_kind") or row.get(fallback_field) or "unknown"
        counts[str(kind)] += 1
    return dict(sorted(counts.items()))


def _table_coverage_stats(
    blocks: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    *,
    preview: int,
) -> dict[str, Any]:
    captions: dict[str, dict[str, Any]] = {}
    block_rows = Counter()
    chunk_rows = Counter()
    unassigned_row_count = 0

    for block in blocks:
        metadata = block.get("metadata") or {}
        table_id = metadata.get("table_id")
        if metadata.get("content_kind") == "table_caption" and table_id:
            captions[str(table_id)] = {
                "table_id": str(table_id),
                "caption_label": metadata.get("caption_label"),
                "page_number": block.get("page_number"),
                "section_path": block.get("section_path") or [],
                "text_preview": _preview(block.get("text"), preview),
                "table_parse_status": metadata.get("table_parse_status"),
            }
        elif metadata.get("content_kind") == "table_row" and table_id:
            block_rows[str(table_id)] += 1
            if metadata.get("table_parse_status") == "unassigned_row":
                unassigned_row_count += 1

    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        table_id = metadata.get("structure_group_id") or metadata.get("table_id")
        if metadata.get("content_kind") == "table_row" and table_id:
            chunk_rows[str(table_id)] += 1

    tables = []
    for table_id, caption in captions.items():
        tables.append(
            {
                **caption,
                "block_row_count": block_rows.get(table_id, 0),
                "chunk_row_count": chunk_rows.get(table_id, 0),
            }
        )

    captions_without_rows = sum(
        1 for table in tables if table["block_row_count"] == 0 and table["chunk_row_count"] == 0
    )
    caption_only_count = sum(1 for table in tables if table["block_row_count"] == 0)
    row_backed_count = sum(1 for table in tables if table["block_row_count"] > 0)
    return {
        "caption_count": len(captions),
        "block_row_count": sum(block_rows.values()),
        "chunk_row_count": sum(chunk_rows.values()),
        "captions_without_rows": captions_without_rows,
        "caption_only_table_count": caption_only_count,
        "row_backed_table_count": row_backed_count,
        "unassigned_row_count": unassigned_row_count,
        "table_groups_with_rows": row_backed_count,
        "table_groups_without_rows": caption_only_count,
        "coverage_ratio": round((len(captions) - captions_without_rows) / len(captions), 3) if captions else 0.0,
        "tables": tables[:40],
    }


def _equation_coverage_stats(blocks: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    equation_labels = []
    explanation_group_ids = set()
    equation_group_ids = set()

    for block in blocks:
        metadata = block.get("metadata") or {}
        kind = metadata.get("content_kind")
        if kind == "equation":
            equation_labels.append(metadata.get("equation_label"))
            if metadata.get("equation_id"):
                equation_group_ids.add(str(metadata["equation_id"]))
        elif kind == "equation_explanation" and metadata.get("equation_id"):
            explanation_group_ids.add(str(metadata["equation_id"]))

    equation_chunk_groups = {
        str((chunk.get("metadata") or {}).get("structure_group_id"))
        for chunk in chunks
        if (chunk.get("metadata") or {}).get("content_kind") == "equation_group"
        and (chunk.get("metadata") or {}).get("structure_group_id")
    }

    return {
        "equation_count": sum(1 for block in blocks if (block.get("metadata") or {}).get("content_kind") == "equation"),
        "equation_explanation_count": sum(
            1 for block in blocks if (block.get("metadata") or {}).get("content_kind") == "equation_explanation"
        ),
        "equation_group_chunk_count": len(equation_chunk_groups),
        "labeled_equation_count": sum(1 for label in equation_labels if label),
        "equations_with_explanations": len(equation_group_ids & explanation_group_ids),
    }


def _figure_caption_stats(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [
        (block.get("metadata") or {}).get("caption_label")
        for block in blocks
        if (block.get("metadata") or {}).get("content_kind") == "figure_caption"
    ]
    return {
        "figure_caption_count": len(labels),
        "labels": [label for label in labels if label][:20],
    }


def _algorithm_stats(blocks: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    block_count = sum(1 for block in blocks if (block.get("metadata") or {}).get("content_kind") == "algorithm")
    chunk_count = sum(1 for chunk in chunks if (chunk.get("metadata") or {}).get("content_kind") == "algorithm")
    labels = []
    for block in blocks:
        metadata = block.get("metadata") or {}
        if metadata.get("content_kind") == "algorithm" and metadata.get("algorithm_label"):
            labels.append(metadata["algorithm_label"])
    return {
        "algorithm_block_count": block_count,
        "algorithm_chunk_count": chunk_count,
        "labels": labels[:20],
    }


def _is_front_matter_noise(block: dict[str, Any]) -> bool:
    metadata = block.get("metadata") or {}
    if metadata.get("content_kind") == "front_matter":
        return False
    text = str(block.get("text") or "").strip()
    page = block.get("page_number")
    path = block.get("section_path") or []
    if page != 1:
        return False
    if path and path[0] in {"Abstract", "I. INTRODUCTION"}:
        return False
    return _is_suspicious_heading(text) or any(marker in text.lower() for marker in ("bsai", "bsds", "information security"))


def _looks_like_front_matter_leakage(block: dict[str, Any]) -> bool:
    metadata = block.get("metadata") or {}
    if metadata.get("content_kind") == "front_matter":
        return False
    if block.get("page_number") != 1:
        return False
    return any(
        marker in str(block.get("text") or "").lower()
        for marker in ("roll no", "department of", "university", "bsai", "bsds", "index terms", "keywords")
    )


def _looks_like_abstract_noise(block: dict[str, Any]) -> bool:
    path = block.get("section_path") or []
    if not path or path[0] != "Abstract":
        return False
    metadata = block.get("metadata") or {}
    if metadata.get("content_kind") == "front_matter":
        return True
    text = str(block.get("text") or "")
    return any(
        marker in text.lower()
        for marker in ("roll no", "department of", "university", "bsai", "bsds", "index terms", "keywords")
    )


def _is_suspicious_heading_block(block: dict[str, Any]) -> bool:
    text = str(block.get("text") or "").strip()
    section_path = block.get("section_path") or []
    if re.match(r"^[A-Z]\.\s+", text) and len(section_path) > 1:
        return False
    return _is_suspicious_heading(text)


def _is_suspicious_heading(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped in {"Abstract", "Transactions"}:
        return stripped == "Transactions"
    if re.match(r"^(?:[IVXLCM]+\.|\d+\.)", stripped):
        return False
    if re.match(r"^[A-Z]\.\s+", stripped):
        return False
    if re.match(r"^(?:Table|TABLE|Fig\.|Figure|Algorithm)\b", stripped):
        return False
    if re.match(r"^\[[0-9]+\]\s+", stripped):
        return True
    if len(stripped.split()) <= 3 and stripped == stripped.upper() and " " not in stripped:
        return True
    if len(stripped.split()) <= 3 and all(part[:1].isupper() for part in stripped.split() if part):
        return True
    if stripped.startswith("SUMMARY OF") or "OF" in stripped and stripped == stripped.upper():
        return True
    return False


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


def _print_audit(audit: dict[str, Any]) -> None:
    print("=== DOCUMENT ===")
    print(f"title: {audit['document']['title']}")
    print(f"document_id: {audit['document']['id']}")
    print(f"workspace_id: {audit['document']['workspace_id']}")
    print(f"source_type: {audit['document']['source_type']}")
    print(f"status: {audit['document']['status']}")
    print()

    summary = audit["summary"]
    print("=== SUMMARY ===")
    print(f"block_count: {summary['block_count']}")
    print(f"chunk_count: {summary['chunk_count']}")
    print(f"block_kind_counts: {summary['block_kind_counts']}")
    print(f"chunk_kind_counts: {summary['chunk_kind_counts']}")
    print(f"front_matter_block_count: {summary['front_matter_block_count']}")
    print(f"excluded_from_chunking_count: {summary['excluded_from_chunking_count']}")
    print(f"front_matter_leakage_count: {summary['front_matter_leakage_count']}")
    print(f"abstract_heading_present: {summary['abstract_heading_present']}")
    print(f"abstract_non_abstract_noise_count: {summary['abstract_non_abstract_noise_count']}")
    print(f"title_emitted_as_heading: {summary['title_emitted_as_heading']}")
    print(f"page_artifact_suppressed_count: {summary['page_artifact_suppressed_count']}")
    print(f"decimal_subsection_heading_count: {summary['decimal_subsection_heading_count']}")
    print(f"merged_equation_fragment_count: {summary['merged_equation_fragment_count']}")
    print(f"equation_fragment_orphan_count: {summary['equation_fragment_orphan_count']}")
    print(f"multi_page_table_header_reuse_count: {summary['multi_page_table_header_reuse_count']}")
    print(f"warning_flags: {summary['warning_flags']}")
    print()

    print("=== STRUCTURE ===")
    print(f"top_level_headings ({audit['headings']['top_level_count']}):")
    for heading in audit["summary"]["top_level_headings"]:
        print(f"- {heading}")
    print()

    print("=== FRONT MATTER ===")
    print(f"block_count: {audit['front_matter']['block_count']}")
    print(f"noise_count: {audit['front_matter']['noise_count']}")
    for sample in audit["front_matter"]["samples"]:
        print(f"- page={sample['page_number']} kind={sample['kind']} preview={sample['text_preview']}")
    for sample in audit["front_matter"]["leakage_samples"]:
        print(f"- leakage page={sample['page_number']} preview={sample['text_preview']}")
    print()

    print("=== ABSTRACT ===")
    print(f"noise_count: {audit['abstract']['noise_count']}")
    for sample in audit["abstract"]["samples"]:
        print(f"- page={sample['page_number']} preview={sample['text_preview']}")
    print()

    print("=== SUSPICIOUS HEADINGS ===")
    print(f"count: {audit['headings']['suspicious_count']}")
    for sample in audit["headings"]["suspicious_samples"]:
        print(f"- page={sample['page_number']} path={sample['section_path']} text={sample['text']}")
    print()

    tables = audit["tables"]
    print("=== TABLES ===")
    print(
        "captions="
        f"{tables['caption_count']} "
        f"block_rows={tables['block_row_count']} "
        f"chunk_rows={tables['chunk_row_count']} "
        f"captions_without_rows={tables['captions_without_rows']} "
        f"caption_only={tables['caption_only_table_count']} "
        f"row_backed={tables['row_backed_table_count']} "
        f"unassigned_rows={tables['unassigned_row_count']} "
        f"coverage_ratio={tables['coverage_ratio']}"
    )
    for table in tables["tables"][:20]:
        print(
            f"- label={table['caption_label']} page={table['page_number']} "
            f"block_rows={table['block_row_count']} chunk_rows={table['chunk_row_count']} "
            f"section={table['section_path']}"
        )
        print(f"  preview: {table['text_preview']}")
    print()

    equations = audit["equations"]
    print("=== EQUATIONS ===")
    print(
        f"equation_count={equations['equation_count']} "
        f"equation_explanation_count={equations['equation_explanation_count']} "
        f"equation_group_chunk_count={equations['equation_group_chunk_count']} "
        f"labeled_equation_count={equations['labeled_equation_count']} "
        f"equations_with_explanations={equations['equations_with_explanations']}"
    )
    print()

    figures = audit["figures"]
    print("=== FIGURES ===")
    print(f"figure_caption_count={figures['figure_caption_count']}")
    if figures["labels"]:
        print(f"labels: {figures['labels']}")
    print()

    algorithms = audit["algorithms"]
    print("=== ALGORITHMS ===")
    print(
        f"algorithm_block_count={algorithms['algorithm_block_count']} "
        f"algorithm_chunk_count={algorithms['algorithm_chunk_count']}"
    )
    if algorithms["labels"]:
        print(f"labels: {algorithms['labels']}")


if __name__ == "__main__":
    asyncio.run(main())
