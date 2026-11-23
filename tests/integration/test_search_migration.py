"""Integration tests for the real PostgreSQL migrations and pg_trgm behavior."""
from pathlib import Path

import pytest

from helpers import apply_sql


pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEARCH_MIGRATION = PROJECT_ROOT / "003_live_unique_search.sql"


def insert_candidate(connection, username: str, *, bio: str = "") -> int:
    return connection.execute(
        "INSERT INTO candidates (main_username, bio) VALUES (%s, %s) RETURNING id",
        (username, bio),
    ).fetchone()[0]


def fuzzy(connection, query: str | None, limit: int | None = 10):
    return connection.execute(
        "SELECT candidate_id, rank FROM search_candidates_fuzzy(%s, %s)",
        (query, limit),
    ).fetchall()


def test_migration_makes_new_and_updated_rows_immediately_searchable(database):
    candidate_id = insert_candidate(database, "orangesunrise")

    # Migration 002 created its materialized snapshot before this insert.
    assert fuzzy(database, "orangesunrise") == []

    apply_sql(database, SEARCH_MIGRATION)
    assert [row[0] for row in fuzzy(database, "orangesunrise")] == [candidate_id]

    database.execute(
        "UPDATE candidates SET main_username = %s WHERE id = %s",
        ("blueharbor", candidate_id),
    )
    assert fuzzy(database, "orangesunrise") == []
    assert [row[0] for row in fuzzy(database, "blueharbor")] == [candidate_id]


def test_migration_collapses_join_multiplication_and_orders_ties(database):
    first_id = insert_candidate(database, "exactneedle")
    second_id = insert_candidate(database, "exactneedle")

    for position in range(2):
        database.execute(
            "INSERT INTO profiles (candidate_id, platform, username) VALUES (%s, %s, %s)",
            (first_id, f"platform-{position}", f"exactneedle-{position}"),
        )
        database.execute(
            "INSERT INTO contacts (candidate_id, contact_type, value) VALUES (%s, %s, %s)",
            (first_id, f"contact-{position}", f"exactneedle-{position}"),
        )
        database.execute(
            """INSERT INTO wallets
               (candidate_id, wallet_type, wallet_address, name_service)
               VALUES (%s, %s, %s, %s)""",
            (first_id, f"wallet-{position}", f"exactneedle-{position}", ""),
        )

    database.execute("REFRESH MATERIALIZED VIEW mv_candidate_search")
    multiplied = database.execute(
        """SELECT count(*)
           FROM mv_candidate_search
           WHERE candidate_id = %s""",
        (first_id,),
    ).fetchone()[0]
    assert multiplied == 8

    apply_sql(database, SEARCH_MIGRATION)
    results = fuzzy(database, "exactneedle")
    assert [row[0] for row in results] == [first_id, second_id]
    assert len({row[0] for row in results}) == len(results)
    assert results[0][1] == results[1][1] == 1.0
    assert database.execute(
        "SELECT to_regclass('mv_candidate_search')"
    ).fetchone()[0] is None


def test_bio_limit_indexes_and_idempotent_reapplication(database):
    ids = [
        insert_candidate(database, f"candidate-{position}", bio="quadratic governance")
        for position in range(3)
    ]
    # Recover when the final statement of migration 002 was not applied.
    database.execute("DROP TABLE known_aliases")
    apply_sql(database, SEARCH_MIGRATION)
    apply_sql(database, SEARCH_MIGRATION)

    assert database.execute(
        "SELECT to_regclass('known_aliases')"
    ).fetchone()[0] == "known_aliases"

    assert [row[0] for row in fuzzy(database, "quadratic governance", 2)] == ids[:2]
    assert [row[0] for row in fuzzy(database, "quadratic governance", 0)] == ids[:1]
    assert fuzzy(database, "   ", 10) == []
    assert fuzzy(database, None, None) == []

    indexes = {
        row[0]
        for row in database.execute(
            """SELECT indexname
               FROM pg_indexes
               WHERE schemaname = current_schema()"""
        ).fetchall()
    }
    assert {
        "idx_profiles_candidate_id",
        "idx_contacts_candidate_id",
        "idx_wallets_candidate_id",
        "idx_known_aliases_candidate_id",
    } <= indexes
