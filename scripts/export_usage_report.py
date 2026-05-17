from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from app.core.config import settings
from app.core.container import AppContainer


async def main() -> None:
    parser = argparse.ArgumentParser(description="Export tenant usage summary as JSON.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    parser.add_argument("--group-by", default="model_profile")
    args = parser.parse_args()

    container = AppContainer(settings)
    await container.startup()
    try:
        response = await container.admin_service.usage_summary(
            tenant_id=UUID(args.tenant_id),
            date_from=args.from_date,
            date_to=args.to_date,
            group_by=args.group_by,
        )
        print(json.dumps(response.model_dump(by_alias=True), indent=2, default=str))
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
