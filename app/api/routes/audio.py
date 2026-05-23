from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.schemas.audio import (
    AudioDocumentDetailResponse,
    CreateAudioUploadUrlRequest,
    CreateAudioUploadUrlResponse,
    IngestAudioDocumentRequest,
    IngestionJobResponse,
)

router = APIRouter()


@router.post("/audio/documents/upload-url", response_model=CreateAudioUploadUrlResponse)
async def create_audio_upload_url(
    payload: CreateAudioUploadUrlRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> CreateAudioUploadUrlResponse:
    return await context.container.audio_ingestion_service.create_upload_target(
        context.workspace_id,
        context.principal,
        payload,
    )


@router.get("/audio/documents/{document_id}", response_model=AudioDocumentDetailResponse)
async def get_audio_document(
    document_id: UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> AudioDocumentDetailResponse:
    return await context.container.audio_ingestion_service.get_audio_document(
        context.workspace_id,
        document_id,
        context.principal,
    )


@router.post("/audio/documents/{document_id}/ingest", response_model=IngestionJobResponse)
async def ingest_audio_document(
    document_id: UUID,
    payload: IngestAudioDocumentRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> IngestionJobResponse:
    return await context.container.audio_ingestion_service.reingest_audio_document(
        context.workspace_id,
        document_id,
        payload,
        context.principal,
    )
