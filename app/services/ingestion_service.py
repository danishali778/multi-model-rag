from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.domain.entities.rag import ExtractedBlock, ExtractedDocument, IngestionTaskPayload
from app.domain.errors import BadRequestError
from app.ingestion.pipeline import build_document_chunks, content_hash, content_hash_bytes
from app.storage.models.ingestion import ChunkReplacementInput, IngestionJobUpdateInput, StageExtractedDocumentInput


@dataclass(slots=True)
class ExtractedDocumentResult:
    document: ExtractedDocument
    source_type: str
    content_hash: str
    should_skip: bool
    processed_storage_bucket: str
    processed_storage_path: str
    embedding_model: str
    chunking_version: str


class IngestionService:
    def __init__(
        self,
        *,
        document_repository: Any,
        ingestion_repository: Any,
        model_router: Any,
        storage: Any,
        parser_registry: Any,
        task_runner: Any,
        telemetry: Any,
        settings: Any,
    ) -> None:
        self._document_repository = document_repository
        self._ingestion_repository = ingestion_repository
        self._model_router = model_router
        self._storage = storage
        self._parser_registry = parser_registry
        self._task_runner = task_runner
        self._telemetry = telemetry
        self._settings = settings

    async def enqueue_ingestion(self, payload: IngestionTaskPayload) -> None:
        await self._task_runner.enqueue_ingestion_job(payload)

    async def ingest_document(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        job_id: UUID,
        text: str,
        metadata: dict[str, Any] | None = None,
        chunking_version: str | None = None,
        embedding_model: str | None = None,
    ) -> dict[str, Any]:
        document = await self._document_repository.get_document_for_ingestion(
            workspace_id=workspace_id,
            document_id=document_id,
        )
        payload = IngestionTaskPayload(
            workspace_id=workspace_id,
            document_id=document_id,
            job_id=job_id,
            chunking_version=chunking_version,
            embedding_model=embedding_model,
        )
        await self._set_job_stage(job_id, stage="extract", stats={"source_type": "text"})
        extracted = await self._extract_inline_document(
            payload,
            text=text,
            metadata=metadata or {},
                title=document.title,
        )
        await self._set_job_stage(
            job_id,
            stage="chunk",
            stats={
                "source_type": extracted.source_type,
                "block_count": len(extracted.document.blocks),
                "warning_count": len(extracted.document.warnings),
            },
        )
        chunk_stats = await self._index_extracted_document(payload, extracted)
        await self._set_job_stage(job_id, stage="finalize", stats=chunk_stats)
        await self._finalize_job(job_id=job_id, document_id=document_id, content_hash=extracted.content_hash, stats=chunk_stats)
        return chunk_stats

    async def process_ingestion_payload(self, payload: IngestionTaskPayload) -> dict[str, Any] | None:
        await self._set_job_stage(payload.job_id, stage="extract")
        extracted = await self.extract_document_content(payload)
        await self._set_job_stage(
            payload.job_id,
            stage="chunk",
            stats={
                "source_type": extracted["source_type"],
                "block_count": extracted.get("block_count", 0),
                "warning_count": extracted.get("warning_count", 0),
            },
        )
        chunk_stats = await self.chunk_and_embed_document(payload)
        await self._set_job_stage(payload.job_id, stage="finalize", stats=chunk_stats)
        await self.finalize_ingestion_job(payload)
        return chunk_stats

    async def extract_document_content(self, payload: IngestionTaskPayload) -> dict[str, Any]:
        document = await self._document_repository.get_document_for_ingestion(
            workspace_id=payload.workspace_id,
            document_id=payload.document_id,
        )
        extracted = await self._extract_document_record(document, payload=payload)
        await self._stage_extracted_document(document_id=payload.document_id, extracted=extracted)
        return {
            "source_type": extracted.source_type,
            "text": extracted.document.text,
            "content_hash": extracted.content_hash,
            "block_count": len(extracted.document.blocks),
            "warning_count": len(extracted.document.warnings),
            "should_skip": extracted.should_skip,
        }

    async def chunk_and_embed_document(self, payload: IngestionTaskPayload) -> dict[str, Any]:
        document = await self._document_repository.get_document_for_ingestion(
            workspace_id=payload.workspace_id,
            document_id=payload.document_id,
        )
        extracted = await self._extract_document_record(document, payload=payload)
        return await self._index_extracted_document(payload, extracted)

    async def finalize_ingestion_job(self, payload: IngestionTaskPayload) -> None:
        document = await self._document_repository.get_document_for_ingestion(
            workspace_id=payload.workspace_id,
            document_id=payload.document_id,
        )
        await self._finalize_job(
            job_id=payload.job_id,
            document_id=payload.document_id,
            content_hash=document.content_hash,
            stats={},
        )

    async def requeue_dead_letter_job(self, payload: IngestionTaskPayload) -> None:
        await self._ingestion_repository.update_job(
            payload.job_id,
            IngestionJobUpdateInput(
                status="queued",
                stage="queued",
                error_code=None,
                error_message=None,
                stats={"requeued": True},
            ),
        )
        await self.enqueue_ingestion(payload)

    async def _extract_document_record(
        self,
        document: Any,
        *,
        payload: IngestionTaskPayload,
    ) -> ExtractedDocumentResult:
        metadata = dict(document.metadata or {})
        inline_text = metadata.get("_inline_text")
        if isinstance(inline_text, str):
            return await self._extract_inline_document(
                payload,
                text=inline_text,
                metadata=metadata,
                title=document.title,
            )

        bucket = document.storage_bucket
        path = document.storage_path
        if not bucket or not path or path == "pending":
            raise BadRequestError("Document storage location is not available for ingestion.")

        raw_bytes = await self._storage.download_bytes(bucket=bucket, path=path)
        parse_metadata = {
            **metadata,
            "filename": metadata.get("_filename") or document.title,
            "storage_path": path,
            "title": document.title,
        }
        parsed = self._parser_registry.parse(
            source_type=document.source_type,
            raw_bytes=raw_bytes,
            metadata=parse_metadata,
        )
        return self._build_extracted_result(
            payload=payload,
            document_id=document.id,
            document=parsed,
            content_digest=content_hash_bytes(raw_bytes),
        )

    async def _extract_inline_document(
        self,
        payload: IngestionTaskPayload,
        *,
        text: str,
        metadata: dict[str, Any],
        title: str | None = None,
    ) -> ExtractedDocumentResult:
        clean_text = text.strip()
        block = ExtractedBlock(
            id=uuid4(),
            block_type="paragraph",
            text=clean_text,
            page_number=None,
            heading_level=None,
            section_path=[],
            order_index=0,
            parent_block_id=None,
            metadata={},
        )
        document = ExtractedDocument(
            text=clean_text,
            detected_source_type=str(metadata.get("source_type") or "text"),
            title=title or metadata.get("title"),
            metadata={**metadata, "source_type": str(metadata.get("source_type") or "text")},
            blocks=[block],
            section_tree=[],
            warnings=[],
        )
        return self._build_extracted_result(
            payload=payload,
            document_id=payload.document_id,
            document=document,
            content_digest=content_hash(clean_text),
        )

    def _build_extracted_result(
        self,
        *,
        payload: IngestionTaskPayload,
        document_id: UUID,
        document: ExtractedDocument,
        content_digest: str,
    ) -> ExtractedDocumentResult:
        extracted_text = document.text.strip()
        chunking_version = payload.chunking_version or getattr(self._settings, "chunking_version", "recursive-v1")
        embedding_model = payload.embedding_model or self._default_embedding_model()
        should_skip = (
            bool(extracted_text)
            and len(extracted_text) < getattr(self._settings, "ingestion_min_text_length", 20)
            and not getattr(self._settings, "ingestion_allow_small_text", False)
        )
        processed_bucket = getattr(self._settings, "supabase_processed_bucket", "processed-documents")
        processed_path = f"workspaces/{payload.workspace_id}/documents/{document_id}/processed/extracted.txt"
        return ExtractedDocumentResult(
            document=document,
            source_type=document.detected_source_type,
            content_hash=content_digest,
            should_skip=should_skip,
            processed_storage_bucket=processed_bucket,
            processed_storage_path=processed_path,
            embedding_model=embedding_model,
            chunking_version=chunking_version,
        )

    async def _stage_extracted_document(
        self,
        *,
        document_id: UUID,
        extracted: ExtractedDocumentResult,
    ) -> None:
        if hasattr(self._storage, "upload_processed_text"):
            await self._storage.upload_processed_text(
                bucket=extracted.processed_storage_bucket,
                path=extracted.processed_storage_path,
                text=extracted.document.text,
            )
        await self._ingestion_repository.stage_extracted_document(
            StageExtractedDocumentInput(
                document_id=document_id,
                content_hash=extracted.content_hash,
                extracted_text=extracted.document.text,
                metadata={**self._public_metadata(extracted.document.metadata), "source_type": extracted.source_type},
                parser_version=getattr(self._settings, "parser_version", "parser-v1"),
                processed_storage_bucket=extracted.processed_storage_bucket,
                processed_storage_path=extracted.processed_storage_path,
                should_skip=extracted.should_skip,
                chunking_version=extracted.chunking_version,
                embedding_model=extracted.embedding_model,
            )
        )

    async def _index_extracted_document(
        self,
        payload: IngestionTaskPayload,
        extracted: ExtractedDocumentResult,
    ) -> dict[str, Any]:
        base_metadata = self._public_metadata(extracted.document.metadata)
        base_metadata["source_type"] = extracted.source_type
        if extracted.document.title:
            base_metadata.setdefault("title", extracted.document.title)
        chunk_count = 0
        embedding_model = extracted.embedding_model
        chunks = build_document_chunks(
            document=extracted.document,
            chunk_size=getattr(self._settings, "chunk_size", 900),
            chunk_overlap=getattr(self._settings, "chunk_overlap", 120),
            metadata=base_metadata,
        )
        if extracted.should_skip:
            chunks = []

        embeddings: list[list[float]] = []
        if chunks:
            embedding_result = await self._model_router.embed_texts([chunk.content for chunk in chunks])
            embeddings = embedding_result.vectors
            embedding_model = embedding_result.model_name
            chunk_count = len(chunks)
        await self._ingestion_repository.replace_document_chunks(
            ChunkReplacementInput(
                workspace_id=payload.workspace_id,
                document_id=payload.document_id,
                blocks=extracted.document.blocks,
                chunks=chunks,
                embeddings=embeddings,
                embedding_model=embedding_model,
                chunking_version=extracted.chunking_version,
            )
        )
        return {
            "source_type": extracted.source_type,
            "content_hash": extracted.content_hash,
            "block_count": len(extracted.document.blocks),
            "chunk_count": chunk_count,
            "warning_count": len(extracted.document.warnings),
            "warnings": list(extracted.document.warnings),
            "skipped_indexing": extracted.should_skip,
        }

    async def _set_job_stage(self, job_id: UUID, *, stage: str, stats: dict[str, Any] | None = None) -> None:
        await self._ingestion_repository.update_job(
            job_id,
            IngestionJobUpdateInput(
                status="processing",
                stage=stage,
                stats=stats or {},
            ),
        )

    async def _finalize_job(
        self,
        *,
        job_id: UUID,
        document_id: UUID,
        content_hash: str | None,
        stats: dict[str, Any],
    ) -> None:
        await self._document_repository.update_document_status(document_id, "succeeded", content_hash=content_hash)
        await self._ingestion_repository.update_job(
            job_id,
            IngestionJobUpdateInput(
                status="succeeded",
                stage="finalize",
                stats=stats,
            ),
        )
        self._telemetry.record_ingestion_job(status="succeeded", stage="finalize")

    def _default_embedding_model(self) -> str:
        try:
            return self._settings.profile_targets("embedding")[0].model_name
        except Exception:
            return getattr(self._settings, "hf_embedding_model", "embedding")

    @staticmethod
    def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in metadata.items() if not key.startswith("_")}
