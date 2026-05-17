from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.core.config import settings
from app.core.container import AppContainer


async def main() -> None:
    parser = argparse.ArgumentParser(description="Requeue a dead-letter ingestion job.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    container = AppContainer(settings)
    await container.startup()
    try:
        response = await container.admin_service.requeue_dead_letter_job(
            tenant_id=UUID(args.tenant_id),
            job_id=UUID(args.job_id),
        )
        print(response.model_dump_json())
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
