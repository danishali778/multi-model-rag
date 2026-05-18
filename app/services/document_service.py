from uuid import UUID
from urllib.parse import urlparse

from app.api.schemas.documents import (
    CreateDocumentRequest,
    CreateDocumentResponse,
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DocumentDetailResponse,
    DocumentListItem,
    DocumentListResponse,
    IngestDocumentRequest,
    IngestionJobResponse,
)
from app.core.config import Settings
from app.domain.entities.rag import IngestionTaskPayload, Principal
from app.domain.errors import BadRequestError
from app.services.ingestion_service import IngestionService
from app.storage.object_store import StorageClient
from app.storage.repositories.rag import RagRepository


class DocumentService:
    def __init__(
        self,
        *,
        repository: RagRepository,
        ingestion_service: IngestionService,
        storage: StorageClient,
        settings: Settings,
    ):
        self.repository = repository
        self.ingestion_service = ingestion_service
        self.storage = storage
        self.settings = settings

    async def create_text_document(
        self,
        tenant_id: UUID,
        principal: Principal,
        payload: CreateDocumentRequest,
    ) -> CreateDocumentResponse:
        text = payload.text.strip()
        if not text:
            raise BadRequestError("Document text cannot be empty.")
        document_id = await self.repository.create_document(
            tenant_id=tenant_id,
            created_by=principal.user_id,
            title=payload.title,
            source_type=payload.source_type,
            source_uri=f"inline://{payload.title}",
            storage_bucket=None,
            storage_path=None,
            content_hash=None,
            status="pending",
            sensitivity=payload.sensitivity,
            metadata={**payload.metadata, "_inline_text": text},
        )
        await self.repository.set_document_acl_groups(
            tenant_id=tenant_id,
            document_id=document_id,
            group_ids=payload.acl_group_ids,
        )
        job_id = await self.repository.create_ingestion_job(tenant_id=tenant_id, document_id=document_id)
        task_payload = IngestionTaskPayload(tenant_id=tenant_id, document_id=document_id, job_id=job_id)
        if self.settings.ingestion_inline_text_sync:
            await self.ingestion_service.ingest_document(
                tenant_id=tenant_id,
                document_id=document_id,
                job_id=job_id,
                text=text,
                metadata=_public_metadata(payload.metadata, payload.title, payload.source_type, payload.sensitivity),
            )
            return CreateDocumentResponse(document_id=document_id, status="indexed", ingestion_job_id=job_id)
        await self.ingestion_service.enqueue_ingestion(task_payload)
        return CreateDocumentResponse(document_id=document_id, status="queued", ingestion_job_id=job_id)

    async def create_upload_target(
        self,
        tenant_id: UUID,
        principal: Principal,
        payload: CreateUploadUrlRequest,
    ) -> CreateUploadUrlResponse:
        source_type = payload.source_type or _infer_source_type(payload.filename, payload.content_type)
        document_title = payload.title or payload.filename
        document_id = await self.repository.create_document(
            tenant_id=tenant_id,
            created_by=principal.user_id,
            title=document_title,
            source_type=source_type,
            source_uri=f"storage://{self.settings.supabase_raw_bucket}/{document_title}",
            storage_bucket=self.settings.supabase_raw_bucket,
            storage_path="pending",
            content_hash=None,
            status="pending",
            sensitivity=payload.sensitivity,
            metadata={
                **payload.metadata,
                "_content_type": payload.content_type,
                "_filename": payload.filename,
            },
        )
        path = f"tenants/{tenant_id}/documents/{document_id}/raw/{payload.filename}"
        await self.repository.update_document_storage(
            document_id=document_id,
            source_uri=f"storage://{self.settings.supabase_raw_bucket}/{path}",
            storage_bucket=self.settings.supabase_raw_bucket,
            storage_path=path,
        )
        await self.repository.set_document_acl_groups(
            tenant_id=tenant_id,
            document_id=document_id,
            group_ids=payload.acl_group_ids,
        )
        target = await self.storage.create_signed_upload_target(
            bucket=self.settings.supabase_raw_bucket,
            path=path,
        )
        normalized_upload_url = _normalize_upload_url(target.upload_url)
        return CreateUploadUrlResponse(
            bucket=target.bucket,
            path=target.path,
            upload_url=normalized_upload_url,
            document_id=document_id,
        )

    async def list_documents(
        self,
        *,
        tenant_id: UUID,
        principal: Principal,
        status: str | None,
        source_type: str | None,
        limit: int,
    ) -> DocumentListResponse:
        rows = await self.repository.list_documents(
            tenant_id=tenant_id,
            user_id=principal.user_id,
            status=status,
            source_type=source_type,
            limit=limit,
        )
        items = [DocumentListItem(**row) for row in rows]
        return DocumentListResponse(items=items)

    async def get_document(
        self,
        tenant_id: UUID,
        document_id: UUID,
        principal: Principal,
    ) -> DocumentDetailResponse:
        row = await self.repository.get_document(tenant_id=tenant_id, document_id=document_id, user_id=principal.user_id)
        return DocumentDetailResponse(**row)

    async def reingest_document(
        self,
        tenant_id: UUID,
        document_id: UUID,
        payload: IngestDocumentRequest,
        principal: Principal,
    ) -> IngestionJobResponse:
        document = await self.repository.get_document_source(
            tenant_id=tenant_id,
            document_id=document_id,
            user_id=principal.user_id,
        )
        job_id = await self.repository.create_ingestion_job(tenant_id=tenant_id, document_id=document_id)
        task_payload = IngestionTaskPayload(
            tenant_id=tenant_id,
            document_id=document_id,
            job_id=job_id,
            force_reindex=payload.force_reindex,
            chunking_version=payload.chunking_version,
            embedding_model=payload.embedding_model,
        )
        text = document["metadata"].get("_inline_text")
        if text and self.settings.ingestion_inline_text_sync:
            await self.ingestion_service.ingest_document(
                tenant_id=tenant_id,
                document_id=document_id,
                job_id=job_id,
                text=text,
                metadata=_public_metadata(
                    document["metadata"],
                    document["title"],
                    document["source_type"],
                    document["sensitivity"],
                ),
            )
        else:
            await self.ingestion_service.enqueue_ingestion(task_payload)
        return await self.get_job(tenant_id, job_id, principal)

    async def get_job(self, tenant_id: UUID, job_id: UUID, principal: Principal) -> IngestionJobResponse:
        row = await self.repository.get_ingestion_job(tenant_id=tenant_id, job_id=job_id, user_id=principal.user_id)
        return IngestionJobResponse(
            ingestion_job_id=row["id"],
            document_id=row["document_id"],
            status=row["status"],
            stage=row["stage"],
            attempts=row["attempts"],
            stats=row["stats"],
            error_code=row["error_code"],
            error_message=row["error_message"],
        )


def _public_metadata(metadata: dict, title: str, source_type: str, sensitivity: str) -> dict:
    public = {key: value for key, value in metadata.items() if not key.startswith("_")}
    public["title"] = title
    public["source_type"] = source_type
    public["sensitivity"] = sensitivity
    return public


def _normalize_upload_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc and parsed.path.startswith("/object/upload/sign/"):
        return parsed._replace(path=f"/storage/v1{parsed.path}").geturl()
    return value


def _infer_source_type(filename: str, content_type: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".md") or content_type == "text/markdown":
        return "markdown"
    if lowered.endswith(".pdf") or content_type == "application/pdf":
        return "pdf"
    if lowered.endswith(".docx") or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "docx"
    if lowered.endswith(".html") or lowered.endswith(".htm") or content_type == "text/html":
        return "html"
    raise BadRequestError(f"Unsupported upload content type '{content_type}'.")
