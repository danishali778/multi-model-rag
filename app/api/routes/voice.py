from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.schemas.voice import VoiceChatRequest, VoiceChatResponse
from app.domain.errors import BadRequestError

router = APIRouter()


@router.post("/voice/chat", response_model=VoiceChatResponse)
async def answer_voice_question(
    context: WorkspaceContext = Depends(get_workspace_context),
    audio_file: UploadFile | None = File(default=None),
    conversation_id: UUID | None = Form(default=None),
    profile: str | None = Form(default=None),
    document_ids: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
    audio_upload_bucket: str | None = Form(default=None),
    audio_upload_path: str | None = Form(default=None),
    mime_type: str | None = Form(default=None),
) -> VoiceChatResponse:
    payload = VoiceChatRequest(
        conversation_id=conversation_id,
        profile=profile,
        document_ids=_parse_document_ids(document_ids),
        metadata=_parse_metadata(metadata),
        audio_upload_bucket=audio_upload_bucket,
        audio_upload_path=audio_upload_path,
        mime_type=audio_file.content_type if audio_file else mime_type,
    )
    await context.container.rate_limiter.check_request(
        principal=context.principal,
        workspace_id=str(context.workspace_id),
        route_key="/v1/voice/chat",
        profile=payload.profile or "balanced",
    )
    raw_bytes = await audio_file.read() if audio_file else None
    filename = audio_file.filename if audio_file else None
    return await context.container.voice_chat_service.answer_voice_turn(
        workspace_id=context.workspace_id,
        principal=context.principal,
        payload=payload,
        audio_bytes=raw_bytes,
        audio_filename=filename,
    )


def _parse_metadata(raw: str | None) -> dict | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequestError("Voice metadata must be valid JSON.") from exc
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise BadRequestError("Voice metadata must be a JSON object.")
    return parsed


def _parse_document_ids(raw: str | None) -> list[UUID] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequestError("Voice document_ids must be a JSON array of UUIDs.") from exc
    if not isinstance(parsed, list):
        raise BadRequestError("Voice document_ids must be a JSON array of UUIDs.")
    try:
        return [UUID(str(item)) for item in parsed]
    except ValueError as exc:
        raise BadRequestError("Voice document_ids must be a JSON array of UUIDs.") from exc
