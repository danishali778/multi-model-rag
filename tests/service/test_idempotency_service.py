from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.domain.errors import ConflictError
from app.services.idempotency_service import IdempotencyService, _request_hash
from app.storage.models.idempotency import IdempotencyRequestRow


class _ResponseModel(BaseModel):
    value: str


def _row(
    *,
    status: str,
    request_hash: str,
    response_body: dict | None = None,
) -> IdempotencyRequestRow:
    now = datetime.now(UTC)
    return IdempotencyRequestRow(
        id=uuid4(),
        user_id=uuid4(),
        workspace_id=uuid4(),
        route_key="/v1/chat",
        idempotency_key="idem-1",
        request_hash=request_hash,
        status=status,
        response_status_code=200 if response_body is not None else None,
        response_body=response_body,
        resource_type=None,
        resource_id=None,
        locked_at=now,
        completed_at=now if status == "completed" else None,
        expires_at=None,
        created_at=now,
        updated_at=now,
    )


class _Repository:
    def __init__(self, claim_result: tuple[bool, IdempotencyRequestRow]):
        self.claim_result = claim_result
        self.completed_calls = []
        self.failed_calls = []

    async def claim_request(self, **kwargs):
        self.claim_kwargs = kwargs
        return self.claim_result

    async def complete_request(self, **kwargs):
        self.completed_calls.append(kwargs)

    async def fail_request(self, **kwargs):
        self.failed_calls.append(kwargs)


def _matching_hash(*, user_id, workspace_id, request_body, path_params=None, route_key="/v1/chat"):
    return _request_hash(
        route_key=route_key,
        user_id=user_id,
        workspace_id=workspace_id,
        path_params=path_params or {},
        request_body=request_body,
    )


def test_execute_persists_completed_response_for_new_claim():
    user_id = uuid4()
    workspace_id = uuid4()
    request_body = {"query": "hello"}
    claimed_row = _row(status="in_progress", request_hash=_matching_hash(user_id=user_id, workspace_id=workspace_id, request_body=request_body))
    repository = _Repository((True, claimed_row))
    service = IdempotencyService(repository)

    async def fake_execute():
        return _ResponseModel(value="created")

    result = asyncio.run(
        service.execute(
            idempotency_key="idem-1",
            route_key="/v1/chat",
            user_id=user_id,
            workspace_id=workspace_id,
            request_body=request_body,
            path_params=None,
            response_model=_ResponseModel,
            execute=fake_execute,
        )
    )

    assert result.value == "created"
    assert repository.completed_calls
    assert repository.completed_calls[0]["response_body"] == {"value": "created"}


def test_execute_replays_completed_response_without_reinvoking_callback():
    user_id = uuid4()
    workspace_id = uuid4()
    request_body = {"query": "hello"}
    repository = _Repository(
        (
            False,
            _row(
                status="completed",
                request_hash=_matching_hash(user_id=user_id, workspace_id=workspace_id, request_body=request_body),
                response_body={"value": "cached"},
            ),
        )
    )
    service = IdempotencyService(repository)
    executed = False

    async def fake_execute():
        nonlocal executed
        executed = True
        return _ResponseModel(value="fresh")

    result = asyncio.run(
        service.execute(
            idempotency_key="idem-1",
            route_key="/v1/chat",
            user_id=user_id,
            workspace_id=workspace_id,
            request_body=request_body,
            path_params=None,
            response_model=_ResponseModel,
            execute=fake_execute,
        )
    )

    assert result.value == "cached"
    assert executed is False


def test_execute_rejects_key_reuse_with_different_payload():
    repository = _Repository((False, _row(status="completed", request_hash="different-hash", response_body={"value": "cached"})))
    service = IdempotencyService(repository)

    async def fake_execute():
        return _ResponseModel(value="fresh")

    with pytest.raises(ConflictError, match="already used with a different request payload"):
        asyncio.run(
            service.execute(
                idempotency_key="idem-1",
                route_key="/v1/chat",
                user_id=uuid4(),
                workspace_id=uuid4(),
                request_body={"query": "hello"},
                path_params=None,
                response_model=_ResponseModel,
                execute=fake_execute,
            )
        )


def test_execute_rejects_duplicate_while_request_is_in_progress():
    user_id = uuid4()
    workspace_id = uuid4()
    request_body = {"query": "hello"}
    repository = _Repository(
        (
            False,
            _row(
                status="in_progress",
                request_hash=_matching_hash(user_id=user_id, workspace_id=workspace_id, request_body=request_body),
            ),
        )
    )
    service = IdempotencyService(repository)

    async def fake_execute():
        return _ResponseModel(value="fresh")

    with pytest.raises(ConflictError, match="already in progress"):
        asyncio.run(
            service.execute(
                idempotency_key="idem-1",
                route_key="/v1/chat",
                user_id=user_id,
                workspace_id=workspace_id,
                request_body=request_body,
                path_params=None,
                response_model=_ResponseModel,
                execute=fake_execute,
            )
        )


def test_execute_marks_request_failed_when_callback_raises():
    user_id = uuid4()
    workspace_id = uuid4()
    request_body = {"query": "hello"}
    claimed_row = _row(status="in_progress", request_hash=_matching_hash(user_id=user_id, workspace_id=workspace_id, request_body=request_body))
    repository = _Repository((True, claimed_row))
    service = IdempotencyService(repository)

    async def fake_execute():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            service.execute(
                idempotency_key="idem-1",
                route_key="/v1/chat",
                user_id=user_id,
                workspace_id=workspace_id,
                request_body=request_body,
                path_params=None,
                response_model=_ResponseModel,
                execute=fake_execute,
            )
        )

    assert repository.failed_calls == [{"request_id": claimed_row.id}]
