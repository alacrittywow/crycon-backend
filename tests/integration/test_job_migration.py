"""PostgreSQL checks for idempotent, leased parser jobs."""

from pathlib import Path

import pytest

from helpers import apply_sql


pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    PROJECT_ROOT / "003_live_unique_search.sql",
    PROJECT_ROOT / "004_storage_integrity.sql",
    PROJECT_ROOT / "005_parser_job_lifecycle.sql",
]


def apply_job_migrations(database):
    for migration in MIGRATIONS:
        apply_sql(database, migration)


def enqueue(database, key="job-key", max_attempts=3):
    return database.execute(
        "SELECT * FROM enqueue_parser_job(%s, %s, %s, %s)",
        ("discovery", "validator", key, max_attempts),
    ).fetchone()


def test_enqueue_is_idempotent_and_claim_has_single_owner(database):
    apply_job_migrations(database)
    first = enqueue(database)
    duplicate = enqueue(database)

    assert first[0] == duplicate[0]
    assert database.execute("SELECT count(*) FROM parser_jobs").fetchone()[0] == 1

    claimed = database.execute(
        "SELECT * FROM claim_parser_job('worker-a', 300)"
    ).fetchone()
    no_second_claim = database.execute(
        "SELECT * FROM claim_parser_job('worker-b', 300)"
    ).fetchone()

    assert claimed[0] == first[0]
    assert database.execute(
        "SELECT status, attempt_count, locked_by FROM parser_jobs WHERE id = %s",
        (first[0],),
    ).fetchone() == ("running", 1, "worker-a")
    assert no_second_claim is None
    assert database.execute(
        "SELECT heartbeat_parser_job(%s, 'worker-b')", (first[0],)
    ).fetchone()[0] is False
    assert database.execute(
        "SELECT complete_parser_job(%s, 'worker-b', 5)", (first[0],)
    ).fetchone()[0] is False
    assert database.execute(
        "SELECT complete_parser_job(%s, 'worker-a', 5)", (first[0],)
    ).fetchone()[0] is True
    assert database.execute(
        "SELECT status, result_count, locked_by FROM parser_jobs WHERE id = %s",
        (first[0],),
    ).fetchone() == ("done", 5, None)


def test_retry_stops_at_max_attempts(database):
    apply_job_migrations(database)
    job_id = enqueue(database, key="retry-key", max_attempts=2)[0]

    database.execute("SELECT * FROM claim_parser_job('worker-a', 300)").fetchone()
    assert database.execute(
        "SELECT fail_parser_job(%s, 'worker-a', 'temporary', true)",
        (job_id,),
    ).fetchone()[0] == "new"

    claimed_again = database.execute(
        "SELECT * FROM claim_parser_job('worker-b', 300)"
    ).fetchone()
    assert database.execute(
        "SELECT attempt_count FROM parser_jobs WHERE id = %s", (job_id,)
    ).fetchone()[0] == 2
    assert database.execute(
        "SELECT fail_parser_job(%s, 'worker-b', 'temporary again', true)",
        (job_id,),
    ).fetchone()[0] == "failed"
    assert database.execute(
        "SELECT * FROM claim_parser_job('worker-c', 300)"
    ).fetchone() is None


def test_stale_lease_is_recovered_and_migration_is_idempotent(database):
    apply_job_migrations(database)
    job_id = enqueue(database, key="stale-key", max_attempts=2)[0]
    database.execute("SELECT * FROM claim_parser_job('dead-worker', 300)").fetchone()
    database.execute(
        "UPDATE parser_jobs SET heartbeat_at = now() - interval '10 minutes' WHERE id = %s",
        (job_id,),
    )

    reclaimed = database.execute(
        "SELECT * FROM claim_parser_job('new-worker', 1)"
    ).fetchone()

    assert reclaimed[0] == job_id
    state = database.execute(
        "SELECT attempt_count, locked_by, error_text FROM parser_jobs WHERE id = %s",
        (job_id,),
    ).fetchone()
    assert state[0:2] == (2, "new-worker")
    assert "queued for retry" in state[2]
    apply_sql(database, MIGRATIONS[-1])
