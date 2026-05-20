from uuid import UUID
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.schemas.documents import (
    CreateDocumentRequest,
    CreateDocumentResponse,
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    IngestDocumentRequest,
    IngestionJobListResponse,
    IngestionJobResponse,
)

router = APIRouter()


@router.post("/documents", response_model=CreateDocumentResponse)
async def create_document(
    payload: CreateDocumentRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> CreateDocumentResponse:
    return await context.container.document_service.create_text_document(context.workspace_id, context.principal, payload)


@router.post("/documents/upload-url", response_model=CreateUploadUrlResponse)
async def create_upload_url(
    payload: CreateUploadUrlRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> CreateUploadUrlResponse:
    response = await context.container.document_service.create_upload_target(context.workspace_id, context.principal, payload)
    parsed = urlparse(response.upload_url)
    if parsed.scheme and parsed.netloc and parsed.path.startswith("/object/upload/sign/"):
        response = response.model_copy(update={"upload_url": parsed._replace(path=f"/storage/v1{parsed.path}").geturl()})
    return response


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    status: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> DocumentListResponse:
    return await context.container.document_service.list_documents(
        workspace_id=context.workspace_id,
        principal=context.principal,
        status=status,
        source_type=source_type,
        limit=limit,
    )


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> DocumentDetailResponse:
    return await context.container.document_service.get_document(context.workspace_id, document_id, context.principal)


@router.post("/documents/{document_id}/ingest", response_model=IngestionJobResponse)
async def ingest_document(
    document_id: UUID,
    payload: IngestDocumentRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> IngestionJobResponse:
    return await context.container.document_service.reingest_document(context.workspace_id, document_id, payload, context.principal)


@router.get("/ingestion-jobs", response_model=IngestionJobListResponse)
async def list_ingestion_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> IngestionJobListResponse:
    return await context.container.document_service.list_jobs(context.workspace_id, context.principal, limit=limit)


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobResponse)
async def get_ingestion_job(
    job_id: UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> IngestionJobResponse:
    return await context.container.document_service.get_job(context.workspace_id, job_id, context.principal)
