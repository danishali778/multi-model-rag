import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.dependencies import WorkspaceContext
from app.api.routes.voice import answer_voice_question, _parse_metadata
from app.api.schemas.voice import VoiceChatResponse
from app.domain.entities.rag import Principal
from app.domain.errors import BadRequestError


def test_voice_chat_route_returns_service_response():
    principal = Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner")
    workspace_id = uuid4()

    async def fake_answer_voice_turn(**kwargs):
        return VoiceChatResponse(
            conversation_id=uuid4(),
            message_id=uuid4(),
            user_transcript="Hello world",
            answer="Remote work is allowed.",
            assistant_audio_url=None,
            sources=[],
            model="groq:mock-model",
            usage=None,
            metadata={"profile": "balanced"},
        )

    captured = {}

    async def fake_check_request(*, principal, workspace_id, route_key, profile=None):
        captured["workspace_id"] = workspace_id
        captured["route_key"] = route_key
        captured["profile"] = profile

    context = WorkspaceContext(
        container=SimpleNamespace(
            voice_chat_service=SimpleNamespace(answer_voice_turn=fake_answer_voice_turn),
            rate_limiter=SimpleNamespace(check_request=fake_check_request),
        ),
        principal=principal,
        workspace_id=workspace_id,
    )

    class _Upload:
        filename = "turn.wav"
        content_type = "audio/wav"

        async def read(self):
            return b"audio"

    upload = _Upload()

    response = asyncio.run(
        answer_voice_question(
            context=context,
            audio_file=upload,
            conversation_id=None,
            profile="balanced",
            document_ids=None,
            metadata=None,
            audio_upload_bucket=None,
            audio_upload_path=None,
            mime_type=None,
        )
    )

    assert response.user_transcript == "Hello world"
    assert captured["workspace_id"] == str(workspace_id)
    assert captured["route_key"] == "/v1/voice/chat"
    assert captured["profile"] == "balanced"


def test_voice_chat_route_rejects_invalid_metadata_shape():
    with pytest.raises(BadRequestError):
        _parse_metadata('["wrong"]')
