from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from app.core.config import settings
from app.core.container import AppContainer
from app.domain.entities.rag import IngestionTaskPayload


async def main() -> None:
    parser = argparse.ArgumentParser(description="Requeue a dead-letter ingestion job.")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    container = AppContainer(settings)
    await container.startup()
    try:
        job = await container.ingestion_repository.get_ingestion_job_internal(
            workspace_id=UUID(args.workspace_id),
            job_id=UUID(args.job_id),
        )
        await container.ingestion_service.requeue_dead_letter_job(
            IngestionTaskPayload(
                workspace_id=job.workspace_id,
                document_id=job.document_id,
                job_id=job.id,
            )
        )
        print(
            json.dumps(
                {
                    "workspace_id": str(job.workspace_id),
                    "job_id": str(job.id),
                    "status": "requeued",
                }
            )
        )
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
