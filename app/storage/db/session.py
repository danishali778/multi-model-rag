from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._migrations_applied = False

    async def startup(self) -> None:
        if self._migrations_applied:
            return
        await self._run_migrations()
        self._migrations_applied = True

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

    async def _run_migrations(self) -> None:
        migration_dir = Path(__file__).resolve().parent / "migrations"
        migration_files = sorted(path for path in migration_dir.glob('*.sql'))
        if not migration_files:
            return
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    create table if not exists schema_migrations (
                        filename text primary key,
                        applied_at timestamptz not null default now()
                    )
                    """
                )
                await conn.commit()

                await cur.execute("select filename from schema_migrations order by filename")
                applied = {row['filename'] for row in await cur.fetchall()}

                if not applied:
                    await cur.execute(
                        """
                        select exists (
                            select 1 from information_schema.tables
                            where table_schema = 'public' and table_name = 'workspaces'
                        ) as has_workspaces,
                        exists (
                            select 1 from information_schema.tables
                            where table_schema = 'public' and table_name = 'tenants'
                        ) as has_tenants
                        """
                    )
                    state = await cur.fetchone()
                    if state['has_workspaces']:
                        for path in migration_files:
                            await cur.execute(
                                "insert into schema_migrations (filename) values (%s) on conflict (filename) do nothing",
                                (path.name,),
                            )
                        await conn.commit()
                        return
                    if state['has_tenants']:
                        for path in migration_files:
                            if path.name < '0006_workspace_schema_cutover.sql':
                                await cur.execute(
                                    "insert into schema_migrations (filename) values (%s) on conflict (filename) do nothing",
                                    (path.name,),
                                )
                        await conn.commit()
                        await cur.execute("select filename from schema_migrations order by filename")
                        applied = {row['filename'] for row in await cur.fetchall()}

                for path in migration_files:
                    if path.name in applied:
                        continue
                    sql = path.read_text()
                    await cur.execute(sql)
                    await cur.execute(
                        "insert into schema_migrations (filename) values (%s) on conflict (filename) do nothing",
                        (path.name,),
                    )
                    await conn.commit()
