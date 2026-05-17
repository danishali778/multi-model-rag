from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_current_principal, get_tenant_access
from app.api.schemas.documents import (
    CreateDocumentRequest,
    CreateDocumentResponse,
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    IngestDocumentRequest,
    IngestionJobResponse,
)
from app.core.container import AppContainer
from app.domain.entities.rag import Principal

router = APIRouter()


@router.post("/tenants/{tenant_id}/documents", response_model=CreateDocumentResponse)
async def create_document(
    tenant_id: UUID,
    payload: CreateDocumentRequest,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> CreateDocumentResponse:
    return await container.document_service.create_text_document(tenant_id, principal, payload)


@router.post("/tenants/{tenant_id}/documents/upload-url", response_model=CreateUploadUrlResponse)
async def create_upload_url(
    tenant_id: UUID,
    payload: CreateUploadUrlRequest,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> CreateUploadUrlResponse:
    return await container.document_service.create_upload_target(tenant_id, principal, payload)


@router.get("/tenants/{tenant_id}/documents", response_model=DocumentListResponse)
async def list_documents(
    tenant_id: UUID,
    status: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> DocumentListResponse:
    return await container.document_service.list_documents(
        tenant_id=tenant_id,
        principal=principal,
        status=status,
        source_type=source_type,
        limit=limit,
    )


@router.get("/tenants/{tenant_id}/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    tenant_id: UUID,
    document_id: UUID,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> DocumentDetailResponse:
    return await container.document_service.get_document(tenant_id, document_id, principal)


@router.post(
    "/tenants/{tenant_id}/documents/{document_id}/ingest",
    response_model=IngestionJobResponse,
)
async def ingest_document(
    tenant_id: UUID,
    document_id: UUID,
    payload: IngestDocumentRequest,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> IngestionJobResponse:
    return await container.document_service.reingest_document(tenant_id, document_id, payload, principal)


@router.get(
    "/tenants/{tenant_id}/ingestion-jobs/{job_id}",
    response_model=IngestionJobResponse,
)
async def get_ingestion_job(
    tenant_id: UUID,
    job_id: UUID,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> IngestionJobResponse:
    return await container.document_service.get_job(tenant_id, job_id, principal)
