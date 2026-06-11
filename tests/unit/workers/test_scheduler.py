import asyncio
from uuid import uuid4

from app.domain.entities.rag import ConnectorSyncRequest
from app.workers.scheduler import Scheduler


def test_scheduler_returns_workspace_scoped_payload():
    request = ConnectorSyncRequest(
        workspace_id=uuid4(),
        connector_type="notion",
        source_key="workspace-knowledge",
        cursor={"page": 2},
    )

    payload = asyncio.run(Scheduler().enqueue_connector_sync(request))

    assert payload["workspace_id"] == str(request.workspace_id)
    assert "tenant_id" not in payload
