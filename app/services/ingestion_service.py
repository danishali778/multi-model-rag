from __future__ import annotations

from uuid import UUID

from app.core.config import Settings
from app.domain.entities.rag import ExtractedDocument, IngestionTaskPayload
from app.domain.errors import BadRequestError, IngestionFailedError, RetryableIngestionError
from app.ingestion.pipeline import build_chunks, content_hash, content_hash_bytes
from app.ingestion.registry import ParserRegistry
from app.llm.router import ModelRouter
from app.storage.object_store import StorageClient
from app.storage.repositories.rag import RagRepository
from app.workers.tasks import IngestionTaskRunner


class IngestionService:
    def __init__(
        self,
        *,
        repository: RagRepository,
        model_router: ModelRouter,
        storage: StorageClient,
        parser_registry: ParserRegistry,
        task_runner: IngestionTaskRunner,
        telemetry,
        settings: Settings,
    ):
        self.repository = repository
        self.model_router = model_router
        self.storage = storage
        self.parser_registry = parser_registry
        self.task_runner = task_runner
        self.telemetry = telemetry
        self.settings = settings

    async def ingest_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        job_id: UUID,
        text: str,
        metadata: dict,
    ) -> None:
        await self.process_inline_text(
            IngestionTaskPayload(
                tenant_id=tenant_id,
                document_id=document_id,
                job_id=job_id,
            ),
            text=text,
            public_metadata=metadata,
        )

    async def enqueue_ingestion(self, payload: IngestionTaskPayload) -> None:
        await self.repository.update_job(
            payload.job_id,
            status="queued",
            stage="queued",
            stats={
                "chunking_version": payload.chunking_version or self.settings.chunking_version,
                "embedding_model": payload.embedding_model or self.settings.hf_embedding_model,
            },
        )
        self.telemetry.record_ingestion_job(status="queued", stage="queued")
        await self.task_runner.enqueue_ingestion_job(payload)

    async def process_ingestion_payload(self, payload: IngestionTaskPayload) -> None:
        document = await self.repository.get_document_for_ingestion(
            tenant_id=payload.tenant_id,
            document_id=payload.document_id,
        )
        await self.repository.update_job(payload.job_id, status="running", stage="extract")
        extracted = await self.extract_document_content(payload)
        await self.repository.update_job(
            payload.job_id,
            status="running",
            stage="chunk",
            stats={
                "parser_version": self.settings.parser_version,
                "source_type": extracted["source_type"],
            },
        )
        await self.chunk_and_embed_document(payload)
        await self.finalize_ingestion_job(payload)

    async def extract_document_content(self, payload: IngestionTaskPayload) -> dict:
        document = await self.repository.get_document_for_ingestion(
            tenant_id=payload.tenant_id,
            document_id=payload.document_id,
        )
        if document["metadata"].get("_inline_text"):
            raw_text = str(document["metadata"]["_inline_text"])
            public_metadata = _public_metadata(
                document["metadata"],
                document["title"],
                document["source_type"],
                document["sensitivity"],
            )
            await self.process_inline_text(payload, text=raw_text, public_metadata=public_metadata)
            return {"source_type": "text", "text": raw_text}

        if not document["storage_bucket"] or not document["storage_path"]:
            raise IngestionFailedError("Document does not have a raw storage object to ingest.")

        raw_bytes = await self.storage.download_bytes(
            bucket=document["storage_bucket"],
            path=document["storage_path"],
        )
        source_type = document["source_type"]
        extracted = self.parser_registry.parse(
            source_type=source_type,
            raw_bytes=raw_bytes,
            metadata={
                **document["metadata"],
                "filename": document["title"],
                "storage_path": document["storage_path"],
            },
        )
        self._validate_extracted_text(extracted)
        hash_value = content_hash_bytes(raw_bytes)
        should_skip = (
            not payload.force_reindex
            and document["content_hash"] == hash_value
            and document["metadata"].get("_chunking_version") == (payload.chunking_version or self.settings.chunking_version)
            and document["metadata"].get("_embedding_model") == (payload.embedding_model or self.settings.hf_embedding_model)
        )
        processed_path = f"tenants/{payload.tenant_id}/documents/{payload.document_id}/processed/extracted.txt"
        await self.storage.upload_processed_text(
            bucket=self.settings.supabase_processed_bucket,
            path=processed_path,
            text=extracted.text,
        )
        metadata = {
            **_public_metadata(document["metadata"], document["title"], document["source_type"], document["sensitivity"]),
            **extracted.metadata,
        }
        await self.repository.stage_extracted_document(
            document_id=payload.document_id,
            content_hash=hash_value,
            extracted_text=extracted.text,
            metadata=metadata,
            parser_version=self.settings.parser_version,
            processed_storage_bucket=self.settings.supabase_processed_bucket,
            processed_storage_path=processed_path,
            should_skip=should_skip,
            chunking_version=payload.chunking_version or self.settings.chunking_version,
            embedding_model=payload.embedding_model or self.settings.hf_embedding_model,
        )
        return {
            "source_type": source_type,
            "text": extracted.text,
            "should_skip": should_skip,
            "processed_storage_path": processed_path,
        }

    async def chunk_and_embed_document(self, payload: IngestionTaskPayload) -> dict:
        document = await self.repository.get_document_for_ingestion(
            tenant_id=payload.tenant_id,
            document_id=payload.document_id,
        )
        staged_text = document["metadata"].get("_staged_text") or document["metadata"].get("_inline_text")
        if not staged_text:
            raise IngestionFailedError("No extracted text is available for chunking.")
        if document["metadata"].get("_skip_indexing"):
            return {"skipped": True}
        public_metadata = _public_metadata(
            document["metadata"],
            document["title"],
            document["source_type"],
            document["sensitivity"],
        )
        chunks = build_chunks(
            str(staged_text),
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            metadata=public_metadata,
        )
        await self.repository.update_job(payload.job_id, status="running", stage="embed")
        try:
            embedding_result = await self.model_router.embed_texts([chunk.content for chunk in chunks])
        except Exception as exc:  # noqa: BLE001
            raise RetryableIngestionError("Embedding provider failed during ingestion.", {"document_id": str(payload.document_id)}) from exc
        await self.repository.replace_document_chunks(
            tenant_id=payload.tenant_id,
            document_id=payload.document_id,
            chunks=chunks,
            embeddings=embedding_result.vectors,
            embedding_model=embedding_result.model_name,
            chunking_version=payload.chunking_version or self.settings.chunking_version,
        )
        await self.repository.record_model_usage(
            tenant_id=payload.tenant_id,
            user_id=None,
            operation="embedding",
            model_profile="embedding",
            provider=embedding_result.provider,
            model_name=embedding_result.model_name,
            input_tokens=embedding_result.input_tokens,
            output_tokens=0,
            estimated_cost_usd=embedding_result.estimated_cost_usd,
            details={
                "document_id": str(payload.document_id),
                "job_id": str(payload.job_id),
                "chunk_count": len(chunks),
                "attempt_count": embedding_result.attempt_count,
                "retry_count": embedding_result.retry_count,
                "fallback_used": embedding_result.fallback_used,
            },
        )
        await self.repository.update_job(
            payload.job_id,
            status="running",
            stage="index",
            stats={
                "chunks_created": len(chunks),
                "tokens_embedded": embedding_result.input_tokens,
            },
        )
        return {"chunks_created": len(chunks)}

    async def finalize_ingestion_job(self, payload: IngestionTaskPayload) -> None:
        document = await self.repository.get_document_for_ingestion(
            tenant_id=payload.tenant_id,
            document_id=payload.document_id,
        )
        if document["metadata"].get("_skip_indexing"):
            await self.repository.update_document_ingestion_metadata(
                payload.document_id,
                metadata_updates={"_skip_indexing": False, "_staged_text": None},
                status="indexed",
            )
            await self.repository.update_job(
                payload.job_id,
                status="succeeded",
                stage="index",
                stats={"noop": True},
            )
            self.telemetry.record_ingestion_job(status="succeeded", stage="index")
            return
        await self.repository.update_document_status(
            payload.document_id,
            "indexed",
            content_hash=document["content_hash"],
        )
        await self.repository.update_document_ingestion_metadata(
            payload.document_id,
            metadata_updates={"_staged_text": None},
            status="indexed",
        )
        await self.repository.update_job(payload.job_id, status="succeeded", stage="index")
        self.telemetry.record_ingestion_job(status="succeeded", stage="index")

    async def requeue_dead_letter_job(self, payload: IngestionTaskPayload) -> None:
        await self.repository.update_job(payload.job_id, status="queued", stage="queued", stats={"requeued": True})
        self.telemetry.record_ingestion_job(status="queued", stage="queued")
        await self.task_runner.enqueue_ingestion_job(payload)

    async def process_inline_text(
        self,
        payload: IngestionTaskPayload,
        *,
        text: str,
        public_metadata: dict,
    ) -> None:
        self._validate_text(text)
        await self.repository.update_job(payload.job_id, status="running", stage="chunk")
        await self.repository.update_document_status(payload.document_id, "processing", content_hash=content_hash(text))
        chunks = build_chunks(
            text,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            metadata=public_metadata,
        )
        await self.repository.update_job(payload.job_id, status="running", stage="embed")
        embedding_result = await self.model_router.embed_texts([chunk.content for chunk in chunks])
        await self.repository.replace_document_chunks(
            tenant_id=payload.tenant_id,
            document_id=payload.document_id,
            chunks=chunks,
            embeddings=embedding_result.vectors,
            embedding_model=payload.embedding_model or embedding_result.model_name,
            chunking_version=payload.chunking_version or self.settings.chunking_version,
        )
        await self.repository.record_model_usage(
            tenant_id=payload.tenant_id,
            user_id=None,
            operation="embedding",
            model_profile="embedding",
            provider=embedding_result.provider,
            model_name=embedding_result.model_name,
            input_tokens=embedding_result.input_tokens,
            output_tokens=0,
            estimated_cost_usd=embedding_result.estimated_cost_usd,
            details={
                "document_id": str(payload.document_id),
                "job_id": str(payload.job_id),
                "chunk_count": len(chunks),
                "attempt_count": embedding_result.attempt_count,
                "retry_count": embedding_result.retry_count,
                "fallback_used": embedding_result.fallback_used,
            },
        )
        await self.repository.update_document_ingestion_metadata(
            payload.document_id,
            metadata_updates={
                "_chunking_version": payload.chunking_version or self.settings.chunking_version,
                "_embedding_model": payload.embedding_model or embedding_result.model_name,
                "_parser_version": self.settings.parser_version,
            },
            status="indexed",
        )
        await self.repository.update_document_status(payload.document_id, "indexed", content_hash=content_hash(text))
        await self.repository.update_job(
            payload.job_id,
            status="succeeded",
            stage="index",
            stats={"chunks_created": len(chunks), "tokens_embedded": embedding_result.input_tokens},
        )
        self.telemetry.record_ingestion_job(status="succeeded", stage="index")

    def _validate_text(self, text: str) -> None:
        if not text.strip():
            raise IngestionFailedError("Document text cannot be empty.")
        if len(text.strip()) < self.settings.ingestion_min_text_length and not self.settings.ingestion_allow_small_text:
            raise IngestionFailedError(
                "Document content is too small to ingest.",
                details={"min_length": self.settings.ingestion_min_text_length},
            )

    def _validate_extracted_text(self, extracted: ExtractedDocument) -> None:
        self._validate_text(extracted.text)


def _public_metadata(metadata: dict, title: str, source_type: str, sensitivity: str) -> dict:
    public = {key: value for key, value in metadata.items() if not key.startswith("_")}
    public["title"] = title
    public["source_type"] = source_type
    public["sensitivity"] = sensitivity
    return public
