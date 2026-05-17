from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.core.config import settings
from app.core.container import AppContainer


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a retrieval evaluation and persist the result.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--model-profile", default="balanced")
    args = parser.parse_args()

    container = AppContainer(settings)
    await container.startup()
    try:
        run_id = await container.evaluation_service.run_retrieval_evaluation(
            tenant_id=UUID(args.tenant_id),
            model_profile=args.model_profile,
        )
        print(run_id)
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
