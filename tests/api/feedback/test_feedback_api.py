import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.api.dependencies import WorkspaceContext
from app.api.routes.feedback import create_feedback
from app.api.schemas.feedback import FeedbackCreateRequest, FeedbackCreateResponse
from app.domain.entities.rag import Principal


class _IdempotencyService:
    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return await kwargs["execute"]()


def test_feedback_route_delegates_to_service():
    message_id = uuid4()
    expected = FeedbackCreateResponse(feedback_id=uuid4(), status="recorded")

    async def fake_create_feedback(**kwargs):
        assert kwargs["message_id"] == message_id
        assert kwargs["payload"].rating == 1
        return expected

    idempotency = _IdempotencyService()
    context = WorkspaceContext(
        container=SimpleNamespace(
            feedback_service=SimpleNamespace(create_feedback=fake_create_feedback),
            idempotency_service=idempotency,
        ),
        principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner"),
        workspace_id=uuid4(),
    )

    response = asyncio.run(
        create_feedback(message_id, FeedbackCreateRequest(rating=1, comment="Useful"), context)
    )

    assert response == expected


def test_feedback_route_uses_idempotency_service_when_key_present():
    message_id = uuid4()
    expected = FeedbackCreateResponse(feedback_id=uuid4(), status="recorded")

    async def fake_create_feedback(**kwargs):
        assert kwargs["message_id"] == message_id
        return expected

    idempotency = _IdempotencyService()
    context = WorkspaceContext(
        container=SimpleNamespace(
            feedback_service=SimpleNamespace(create_feedback=fake_create_feedback),
            idempotency_service=idempotency,
        ),
        principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner"),
        workspace_id=uuid4(),
    )

    response = asyncio.run(
        create_feedback(
            message_id,
            FeedbackCreateRequest(rating=1, comment="Useful"),
            context,
            idempotency_key="idem-feedback-1",
        )
    )

    assert response == expected
    assert idempotency.calls[0]["idempotency_key"] == "idem-feedback-1"
    assert idempotency.calls[0]["route_key"] == "/v1/messages/{message_id}/feedback"
