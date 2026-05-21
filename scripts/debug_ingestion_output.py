from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.core.config import get_settings
from app.storage.db.session import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect stored document blocks and retrieval chunks for a document."
    )
    parser.add_argument("--document-id", help="Exact document UUID to inspect.")
    parser.add_argument(
        "--title",
        help="Find the most recent document with this exact title if document id is not provided.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="How many recent documents to show when no selector is provided.",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=260,
        help="Preview length for block/chunk text output.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    db = Database(get_settings())

    async with db.connection() as conn:
        async with conn.cursor() as cursor:
            if args.document_id:
                document = await fetch_document_by_id(cursor, args.document_id)
                if not document:
                    raise SystemExit(f"Document not found: {args.document_id}")
                await inspect_document(cursor, document["id"], args.preview)
                return

            if args.title:
                document = await fetch_document_by_title(cursor, args.title)
                if not document:
                    raise SystemExit(f"No document found with title: {args.title}")
                await inspect_document(cursor, document["id"], args.preview)
                return

            await list_recent_documents(cursor, args.limit)


async def fetch_document_by_id(cursor: Any, document_id: str) -> dict[str, Any] | None:
    await cursor.execute(
        """
        select id, title, created_at
        from documents
        where id = %s::uuid
        """,
        (document_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def fetch_document_by_title(cursor: Any, title: str) -> dict[str, Any] | None:
    await cursor.execute(
        """
        select id, title, created_at
        from documents
        where title = %s
        order by created_at desc
        limit 1
        """,
        (title,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_recent_documents(cursor: Any, limit: int) -> None:
    await cursor.execute(
        """
        select id, title, created_at
        from documents
        order by created_at desc
        limit %s
        """,
        (limit,),
    )
    rows = await cursor.fetchall()

    if not rows:
        print("No documents found.")
        return

    print("Recent documents:\n")
    for row in rows:
        print(f"{row['id']}  {row['title']}  {row['created_at']}")


async def inspect_document(cursor: Any, document_id: str, preview_length: int) -> None:
    await cursor.execute(
        """
        select id, title, created_at
        from documents
        where id = %s::uuid
        """,
        (document_id,),
    )
    meta = await cursor.fetchone()

    if not meta:
        raise SystemExit(f"Document not found: {document_id}")

    print(f"Document: {meta['title']}")
    print(f"ID: {meta['id']}")
    print(f"Created: {meta['created_at']}")
    print()

    await print_blocks(cursor, document_id, preview_length)
    print()
    await print_chunks(cursor, document_id, preview_length)


async def print_blocks(cursor: Any, document_id: str, preview_length: int) -> None:
    if not await table_exists(cursor, "document_blocks"):
        print("=== BLOCKS ===")
        print("Table missing: document_blocks")
        return

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
    rows = await cursor.fetchall()

    print("=== BLOCKS ===")
    if not rows:
        print("No document_blocks rows found.")
        return

    kind_counts: dict[str, int] = {}
    for row in rows:
        metadata = row["metadata"] or {}
        content_kind = metadata.get("content_kind") or row["block_type"]
        kind_counts[content_kind] = kind_counts.get(content_kind, 0) + 1
    print(f"block_kind_counts={json.dumps(kind_counts, sort_keys=True)}")

    for row in rows:
        metadata = row["metadata"] or {}
        print("-" * 80)
        print(
            f"order={row['order_index']} "
            f"type={row['block_type']} "
            f"heading={row['heading_level']} "
            f"page={row['page_number']}"
        )
        print(f"section_title={row['section_title']}")
        print(f"subsection_title={row['subsection_title']}")
        print(f"section_path={json.dumps(row['section_path'] or [])}")
        print(f"parent_block_id={row['parent_block_id']}")
        print(
            "content_kind="
            f"{metadata.get('content_kind')} "
            f"table_id={metadata.get('table_id')} "
            f"equation_id={metadata.get('equation_id')} "
            f"algorithm_id={metadata.get('algorithm_id')} "
            f"caption_label={metadata.get('caption_label')}"
        )
        print(preview_text(row["text"], preview_length))


async def print_chunks(cursor: Any, document_id: str, preview_length: int) -> None:
    if not await table_exists(cursor, "document_chunks"):
        print("=== CHUNKS ===")
        print("Table missing: document_chunks")
        return

    required_columns = {
        "id",
        "chunk_role",
        "chunk_type",
        "page_number",
        "section_title",
        "subsection_title",
        "section_path",
        "parent_block_id",
        "block_order_start",
        "block_order_end",
        "token_count",
        "metadata",
        "content",
        "created_at",
    }
    existing_columns = await table_columns(cursor, "document_chunks")
    missing_columns = sorted(required_columns - existing_columns)
    if missing_columns:
        print("=== CHUNKS ===")
        print(
            "Table present but missing structure-aware columns: "
            + ", ".join(missing_columns)
        )
        legacy_columns = {"id", "chunk_index", "token_count", "content", "created_at"}
        if legacy_columns.issubset(existing_columns):
            await print_legacy_chunks(cursor, document_id, preview_length)
        return

    await cursor.execute(
        """
        select
            id,
            chunk_role,
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
            created_at
        """,
        (document_id,),
    )
    rows = await cursor.fetchall()

    print("=== CHUNKS ===")
    if not rows:
        print("No document_chunks rows found.")
        return

    kind_counts: dict[str, int] = {}
    for row in rows:
        metadata = row["metadata"] or {}
        content_kind = metadata.get("content_kind") or row["chunk_type"]
        kind_counts[content_kind] = kind_counts.get(content_kind, 0) + 1
    print(f"chunk_kind_counts={json.dumps(kind_counts, sort_keys=True)}")

    for row in rows:
        metadata = row["metadata"] or {}
        print("=" * 80)
        print(
            f"id={row['id']} "
            f"role={row['chunk_role']} "
            f"type={row['chunk_type']} "
            f"page={row['page_number']} "
            f"tokens={row['token_count']}"
        )
        print(f"section_title={row['section_title']}")
        print(f"subsection_title={row['subsection_title']}")
        print(f"section_path={json.dumps(row['section_path'] or [])}")
        print(f"parent_block_id={row['parent_block_id']}")
        print(f"block_range={row['block_order_start']}..{row['block_order_end']}")
        print(
            "content_kind="
            f"{metadata.get('content_kind')} "
            f"group={metadata.get('structure_group_id')} "
            f"caption_label={metadata.get('caption_label')} "
            f"equation_label={metadata.get('equation_label')} "
            f"algorithm_label={metadata.get('algorithm_label')}"
        )
        print(preview_text(row["content"], preview_length))


def preview_text(value: str, length: int) -> str:
    normalized = " ".join((value or "").split())
    if len(normalized) <= length:
        return normalized
    return normalized[:length].rstrip() + "..."


async def print_legacy_chunks(cursor: Any, document_id: str, preview_length: int) -> None:
    print("Legacy chunk rows:\n")
    await cursor.execute(
        """
        select id, chunk_index, token_count, content, created_at
        from document_chunks
        where document_id = %s::uuid
        order by chunk_index, created_at
        """,
        (document_id,),
    )
    rows = await cursor.fetchall()
    if not rows:
        print("No legacy document_chunks rows found.")
        return

    for row in rows:
        print("=" * 80)
        print(
            f"id={row['id']} "
            f"chunk_index={row['chunk_index']} "
            f"tokens={row['token_count']} "
            f"created_at={row['created_at']}"
        )
        print(preview_text(row["content"], preview_length))


async def table_exists(cursor: Any, table_name: str) -> bool:
    await cursor.execute("select to_regclass(%s) as name", (f"public.{table_name}",))
    row = await cursor.fetchone()
    return bool(row and row["name"])


async def table_columns(cursor: Any, table_name: str) -> set[str]:
    await cursor.execute(
        """
        select column_name
        from information_schema.columns
        where table_schema = 'public' and table_name = %s
        """,
        (table_name,),
    )
    rows = await cursor.fetchall()
    return {row["column_name"] for row in rows}


if __name__ == "__main__":
    asyncio.run(main())
