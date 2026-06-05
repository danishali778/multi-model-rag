from __future__ import annotations

import asyncio

from app.core.config import settings
from app.storage.db.session import Database


async def main() -> None:
    database = Database(settings)
    await database.startup()
    try:
        if not await database.health_check():
            raise RuntimeError("Database health check failed.")
        async with database.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("select count(*) as count from schema_migrations")
                migration_count = (await cur.fetchone())["count"]
                await cur.execute(
                    """
                    select exists (
                        select 1 from information_schema.tables
                        where table_schema = 'public' and table_name = 'evaluation_runs'
                    ) as has_evaluation_runs
                    """
                )
                has_evaluation_runs = (await cur.fetchone())["has_evaluation_runs"]
        if migration_count < 1 or not has_evaluation_runs:
            raise RuntimeError("Bootstrap verification failed.")
        print(
            {
                "migration_count": migration_count,
                "has_evaluation_runs": has_evaluation_runs,
            }
        )
    finally:
        await database.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
