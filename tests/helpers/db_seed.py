from __future__ import annotations

import psycopg


def run_sql(dsn: str, statement: str, params: tuple | None = None) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(statement, params or ())
