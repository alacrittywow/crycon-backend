import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from helpers import apply_sql


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_MIGRATIONS = (
    PROJECT_ROOT / "schema_v1.sql",
    PROJECT_ROOT / "002_search_improvements.sql",
)


@pytest.fixture
def database():
    database_url = os.getenv("CRYCON_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("CRYCON_TEST_DATABASE_URL is not set")

    schema_name = f"crycon_test_{uuid.uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
        connection.execute(
            sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(schema_name)
            )
        )
        try:
            for migration in BASE_MIGRATIONS:
                apply_sql(connection, migration)
            yield connection
        finally:
            connection.execute("SET search_path TO public")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
