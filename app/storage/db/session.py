from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    @asynccontextmanager
    async def connection(self):
        if not self.settings.supabase_db_url:
            raise RuntimeError("SUPABASE_DB_URL is not configured.")
        conn = await psycopg.AsyncConnection.connect(
            self.settings.supabase_db_url,
            row_factory=dict_row,
            autocommit=False,
        )
        try:
            yield conn
        finally:
            await conn.close()

    async def health_check(self) -> bool:
        if not self.settings.supabase_db_url:
            return False
        try:
            async with self.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("select 1")
                    await cur.fetchone()
            return True
        except Exception:
            return False
