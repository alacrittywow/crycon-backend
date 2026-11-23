"""Security migration keeps all storage private by default."""
from pathlib import Path

import pytest

from helpers import apply_sql


pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = tuple(
    PROJECT_ROOT / name
    for name in (
        "003_live_unique_search.sql",
        "004_storage_integrity.sql",
        "005_parser_job_lifecycle.sql",
        "006_api_security.sql",
    )
)


def test_security_migration_enables_rls_and_removes_public_rpc_access(database):
    for migration in MIGRATIONS:
        apply_sql(database, migration)

    rls = dict(database.execute(
        """SELECT relname, relrowsecurity
           FROM pg_class
           JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
           WHERE nspname = current_schema()
             AND relname = ANY(%s)""",
        ([
            "candidates", "profiles", "contacts", "wallets", "evidence",
            "parser_jobs", "known_aliases",
        ],),
    ).fetchall())
    assert rls and all(rls.values())

    public_execute = database.execute(
        """SELECT EXISTS (
               SELECT 1
               FROM pg_proc p
               CROSS JOIN LATERAL aclexplode(
                   coalesce(p.proacl, acldefault('f', p.proowner))
               ) acl
               WHERE p.oid = 'search_candidates_fuzzy(text,integer)'::regprocedure
                 AND acl.grantee = 0
                 AND acl.privilege_type = 'EXECUTE'
           )"""
    ).fetchone()[0]
    assert public_execute is False

    apply_sql(database, MIGRATIONS[-1])
