"""PostgreSQL checks for atomic discovery and new-write integrity rules."""
from pathlib import Path

import psycopg
import pytest

from helpers import apply_sql


pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEARCH_MIGRATION = PROJECT_ROOT / "003_live_unique_search.sql"
STORAGE_MIGRATION = PROJECT_ROOT / "004_storage_integrity.sql"


def apply_storage_migrations(database):
    apply_sql(database, SEARCH_MIGRATION)
    apply_sql(database, STORAGE_MIGRATION)


def create_discovered(database, *, platform="GitHub", username="Alice", score=70):
    return database.execute(
        """SELECT * FROM create_discovered_candidate(
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )""",
        (
            platform, username, "Alice", "Solana validator",
            "https://github.com/alice", "https://github.com/alice",
            "validator", score, "valid",
            "Discovered by parser. Matched keyword: validator",
        ),
    ).fetchone()


def test_atomic_rpc_is_case_insensitive_and_idempotent(database):
    apply_storage_migrations(database)

    created = create_discovered(database)
    existing = create_discovered(database, platform=" github ", username=" alice ")

    assert created[0] == "created"
    assert existing[0] == "exists"
    assert existing[1:3] == created[1:3]
    assert existing[3] is None
    assert database.execute("SELECT count(*) FROM candidates").fetchone()[0] == 1
    assert database.execute("SELECT count(*) FROM profiles").fetchone()[0] == 1
    assert database.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1


def test_failed_final_insert_rolls_back_candidate_and_profile(database):
    apply_storage_migrations(database)

    # This temporary rule forces the last of the three inserts to fail.
    database.execute(
        """ALTER TABLE evidence ADD CONSTRAINT reject_test_evidence
           CHECK (evidence_text <> 'force rollback')"""
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        database.execute(
            """SELECT * FROM create_discovered_candidate(
                'github', 'rollback-user', '', '', '', '', '',
                40, 'needs_review', 'force rollback'
            )"""
        )

    assert database.execute("SELECT count(*) FROM candidates").fetchone()[0] == 0
    assert database.execute("SELECT count(*) FROM profiles").fetchone()[0] == 0
    assert database.execute("SELECT count(*) FROM evidence").fetchone()[0] == 0


def test_not_valid_constraints_protect_new_rows_and_updated_at(database):
    # Historical invalid data does not block rollout.
    candidate_id = database.execute(
        """INSERT INTO candidates (main_username, relevance_score)
           VALUES ('legacy-bad-score', 150) RETURNING id"""
    ).fetchone()[0]
    apply_storage_migrations(database)
    apply_sql(database, STORAGE_MIGRATION)

    assert database.execute(
        "SELECT relevance_score FROM candidates WHERE id = %s", (candidate_id,)
    ).fetchone()[0] == 150
    with pytest.raises(psycopg.errors.CheckViolation):
        database.execute(
            "INSERT INTO candidates (main_username, relevance_score) VALUES ('new-bad', 150)"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        database.execute(
            "INSERT INTO parser_jobs (job_type, status) VALUES ('discovery', 'mystery')"
        )

    valid_id, before = database.execute(
        """INSERT INTO candidates (main_username, relevance_score)
           VALUES ('valid-candidate', 50) RETURNING id, updated_at"""
    ).fetchone()
    database.execute("SELECT pg_sleep(0.001)")
    database.execute(
        "UPDATE candidates SET display_name = 'changed' WHERE id = %s",
        (valid_id,),
    )
    after = database.execute(
        "SELECT updated_at FROM candidates WHERE id = %s", (valid_id,)
    ).fetchone()[0]
    assert after > before
