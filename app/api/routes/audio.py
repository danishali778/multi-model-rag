from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.idempotency import execute_idempotent
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CreateAudioUploadUrlResponse:
    return await execute_idempotent(
        idempotency_service=context.container.idempotency_service,
        idempotency_key=idempotency_key,
        route_key="/v1/audio/documents/upload-url",
        user_id=context.principal.user_id,
        workspace_id=context.workspace_id,
        request_body=payload.model_dump(mode="json"),
        path_params=None,
        response_model=CreateAudioUploadUrlResponse,
        execute=lambda: context.container.audio_ingestion_service.create_upload_target(
            context.workspace_id,
            context.principal,
            payload,
        ),
        replay_transform=lambda record, body: _refresh_audio_upload_replay(context, body),
        resource_type="audio_upload",
        resource_id_selector=lambda response: response.document_id,
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IngestionJobResponse:
    return await execute_idempotent(
        idempotency_service=context.container.idempotency_service,
        idempotency_key=idempotency_key,
        route_key="/v1/audio/documents/{document_id}/ingest",
        user_id=context.principal.user_id,
        workspace_id=context.workspace_id,
        request_body=payload.model_dump(mode="json"),
        path_params={"document_id": document_id},
        response_model=IngestionJobResponse,
        execute=lambda: context.container.audio_ingestion_service.reingest_audio_document(
            context.workspace_id,
            document_id,
            payload,
            context.principal,
        ),
        resource_type="ingestion_job",
        resource_id_selector=lambda response: response.ingestion_job_id,
    )


async def _refresh_audio_upload_replay(context: WorkspaceContext, payload: dict) -> dict:
    response = CreateAudioUploadUrlResponse.model_validate(payload)
    refreshed = await context.container.audio_ingestion_service.refresh_upload_target_response(response)
    return refreshed.model_dump(mode="json")
