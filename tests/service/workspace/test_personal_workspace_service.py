import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.domain.entities.rag import Principal
from app.services.personal_workspace_service import PersonalWorkspaceService
from tests.helpers.fake_repositories import RecordingWorkspaceRepository


def test_ensure_workspace_for_identity_returns_existing_workspace():
    workspace_id = uuid4()
    repository = RecordingWorkspaceRepository(primary_workspace=SimpleNamespace(id=workspace_id, role="owner"))
    service = PersonalWorkspaceService(repository)

    resolved = asyncio.run(service.ensure_workspace_for_identity(user_id=uuid4(), email="dev@example.com"))

    assert resolved == workspace_id
    assert repository.created_payloads == []


def test_resolve_workspace_for_principal_creates_missing_workspace_and_sets_owner_role():
    repository = RecordingWorkspaceRepository(primary_workspace=None)
    service = PersonalWorkspaceService(repository)
    principal = Principal(user_id=uuid4(), email="dev@example.com", auth_method="jwt")

    workspace_id = asyncio.run(service.resolve_workspace_for_principal(principal))

    assert principal.role == "owner"
    assert str(workspace_id)
    assert len(repository.created_payloads) == 1
