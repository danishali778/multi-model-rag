from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest

from app.core.config import settings
from app.storage.db.session import Database


def _migration_count() -> int:
    migration_dir = Path(__file__).resolve().parents[3] / "app" / "storage" / "db" / "migrations"
    return len(list(migration_dir.glob("*.sql")))


def _admin_dsn() -> str:
    if not settings.supabase_db_url:
        pytest.skip("Integration DB URL is not configured.")
    parsed = urlparse(settings.supabase_db_url)
    admin_path = "/postgres"
    return parsed._replace(path=admin_path).geturl()


def _probe_admin_connection() -> None:
    try:
        with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Integration database is unreachable: {exc}")


def _database_dsn(db_name: str) -> str:
    parsed = urlparse(_admin_dsn())
    return parsed._replace(path=f"/{db_name}").geturl()


def _create_database(db_name: str) -> None:
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'drop database if exists "{db_name}" with (force)')
            cur.execute(f'create database "{db_name}"')


def _drop_database(db_name: str) -> None:
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'drop database if exists "{db_name}" with (force)')


def _run_startup(dsn: str) -> None:
    asyncio.run(Database(SimpleNamespace(supabase_db_url=dsn)).startup())


def test_fresh_database_bootstrap_is_idempotent():
    _probe_admin_connection()
    db_name = f"mmrag_bootstrap_{uuid4().hex[:8]}"
    dsn = _database_dsn(db_name)
    _create_database(db_name)

    try:
        _run_startup(dsn)
        _run_startup(dsn)

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from schema_migrations")
                migration_count = cur.fetchone()[0]
                cur.execute(
                    """
                    select exists (
                        select 1 from information_schema.tables
                        where table_schema = 'public' and table_name = 'workspaces'
                    ),
                    exists (
                        select 1 from information_schema.tables
                        where table_schema = 'public' and table_name = 'evaluation_runs'
                    )
                    """
                )
                has_workspaces, has_evaluation_runs = cur.fetchone()
        assert migration_count == _migration_count()
        assert has_workspaces is True
        assert has_evaluation_runs is True
    finally:
        _drop_database(db_name)


def test_workspace_bootstrap_without_ledger_recreates_evaluation_runs():
    _probe_admin_connection()
    db_name = f"mmrag_workspace_{uuid4().hex[:8]}"
    dsn = _database_dsn(db_name)
    _create_database(db_name)

    try:
        _run_startup(dsn)

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("delete from schema_migrations")
                cur.execute("drop table if exists evaluation_runs cascade")

        _run_startup(dsn)

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select exists (
                        select 1 from information_schema.tables
                        where table_schema = 'public' and table_name = 'evaluation_runs'
                    )
                    """
                )
                has_evaluation_runs = cur.fetchone()[0]
                cur.execute(
                    "select exists (select 1 from schema_migrations where filename = '0011_workspace_evaluation_runs.sql')"
                )
                has_0011 = cur.fetchone()[0]

        assert has_evaluation_runs is True
        assert has_0011 is True
    finally:
        _drop_database(db_name)
