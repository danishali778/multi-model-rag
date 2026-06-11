from __future__ import annotations

import hashlib
import json
from typing import Any, Awaitable, Callable, TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.domain.errors import ConflictError
from app.storage.models.idempotency import IdempotencyRequestRow

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class IdempotencyService:
    def __init__(self, repository) -> None:
        self.repository = repository

    async def execute(
        self,
        *,
        idempotency_key: str,
        route_key: str,
        user_id: UUID,
        workspace_id: UUID | None,
        request_body: dict[str, Any],
        path_params: dict[str, Any] | None,
        response_model: type[ResponseModelT],
        execute: Callable[[], Awaitable[ResponseModelT]],
        replay_transform: Callable[[IdempotencyRequestRow, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
        resource_type: str | None = None,
        resource_id_selector: Callable[[ResponseModelT], UUID | None] | None = None,
    ) -> ResponseModelT:
        request_hash = _request_hash(
            route_key=route_key,
            user_id=user_id,
            workspace_id=workspace_id,
            path_params=path_params or {},
            request_body=request_body,
        )
        claimed, row = await self.repository.claim_request(
            user_id=user_id,
            workspace_id=workspace_id,
            route_key=route_key,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if not claimed:
            if row.request_hash != request_hash:
                raise ConflictError(
                    "This Idempotency-Key was already used with a different request payload.",
                    details={"route_key": route_key, "idempotency_key": idempotency_key},
                )
            if row.status == "completed" and row.response_body is not None:
                payload = dict(row.response_body)
                if replay_transform is not None:
                    payload = await replay_transform(row, payload)
                return response_model.model_validate(payload)
            raise ConflictError(
                "A request with this Idempotency-Key is already in progress.",
                details={"route_key": route_key, "idempotency_key": idempotency_key},
            )

        try:
            result = await execute()
        except Exception:
            await self.repository.fail_request(request_id=row.id)
            raise

        response_body = result.model_dump(mode="json")
        resource_id = resource_id_selector(result) if resource_id_selector is not None else None
        await self.repository.complete_request(
            request_id=row.id,
            response_status_code=200,
            response_body=response_body,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        return result


def _request_hash(
    *,
    route_key: str,
    user_id: UUID,
    workspace_id: UUID | None,
    path_params: dict[str, Any],
    request_body: dict[str, Any],
) -> str:
    canonical = {
        "route_key": route_key,
        "user_id": str(user_id),
        "workspace_id": str(workspace_id) if workspace_id is not None else None,
        "path_params": _normalize(path_params),
        "request_body": _normalize(request_body),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    return value
