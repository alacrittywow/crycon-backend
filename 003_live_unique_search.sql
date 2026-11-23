-- Replace the stale, row-multiplying materialized search view from migration 002.
-- Search now reads the base tables, so inserts, updates and deletes are visible
-- immediately. Ranking starts from candidates, yielding at most one row per ID.

DROP FUNCTION IF EXISTS search_candidates_fuzzy(text, integer);
DROP MATERIALIZED VIEW IF EXISTS mv_candidate_search;

-- Migration 002 originally introduced aliases as its final statement. Recreate
-- the table defensively so an interrupted/partially applied 002 can recover.
CREATE TABLE IF NOT EXISTS known_aliases (
    alias text PRIMARY KEY,
    candidate_id bigint NOT NULL REFERENCES candidates(id) ON DELETE CASCADE
);

-- Support candidate-scoped lookups used by the live ranking query and card reads.
CREATE INDEX IF NOT EXISTS idx_profiles_candidate_id ON profiles(candidate_id);
CREATE INDEX IF NOT EXISTS idx_contacts_candidate_id ON contacts(candidate_id);
CREATE INDEX IF NOT EXISTS idx_wallets_candidate_id ON wallets(candidate_id);
CREATE INDEX IF NOT EXISTS idx_known_aliases_candidate_id ON known_aliases(candidate_id);

CREATE OR REPLACE FUNCTION search_candidates_fuzzy(
    search_query text,
    limit_rows integer DEFAULT 10
)
RETURNS TABLE(candidate_id bigint, rank real)
LANGUAGE sql
STABLE
AS $$
    WITH params AS (
        SELECT
            btrim(coalesce(search_query, '')) AS query,
            greatest(1, least(coalesce(limit_rows, 10), 100)) AS row_limit
    ),
    matches AS (
        SELECT
            c.id AS candidate_id,
            greatest(
                similarity(coalesce(c.main_username, ''), p.query),
                similarity(coalesce(c.display_name, ''), p.query),
                similarity(coalesce(c.bio, ''), p.query)
            ) AS rank
        FROM candidates c
        CROSS JOIN params p
        WHERE p.query <> ''
          AND (
              c.main_username % p.query
              OR c.display_name % p.query
              OR c.bio % p.query
          )

        UNION ALL

        SELECT pr.candidate_id, similarity(coalesce(pr.username, ''), p.query)
        FROM profiles pr
        CROSS JOIN params p
        WHERE p.query <> ''
          AND pr.candidate_id IS NOT NULL
          AND pr.username % p.query

        UNION ALL

        SELECT ct.candidate_id, similarity(coalesce(ct.value, ''), p.query)
        FROM contacts ct
        CROSS JOIN params p
        WHERE p.query <> ''
          AND ct.candidate_id IS NOT NULL
          AND ct.value % p.query

        UNION ALL

        SELECT
            w.candidate_id,
            greatest(
                similarity(coalesce(w.wallet_address, ''), p.query),
                similarity(coalesce(w.name_service, ''), p.query)
            )
        FROM wallets w
        CROSS JOIN params p
        WHERE p.query <> ''
          AND w.candidate_id IS NOT NULL
          AND (
              w.wallet_address % p.query
              OR w.name_service % p.query
          )
    ),
    ranked AS (
        SELECT matches.candidate_id, max(matches.rank)::real AS rank
        FROM matches
        GROUP BY matches.candidate_id
    )
    SELECT ranked.candidate_id, ranked.rank
    FROM ranked
    WHERE ranked.rank > 0
    ORDER BY ranked.rank DESC, ranked.candidate_id ASC
    LIMIT (SELECT row_limit FROM params);
$$;

COMMENT ON FUNCTION search_candidates_fuzzy(text, integer) IS
    'Live pg_trgm search. Returns unique candidates ordered by rank then ID; limit is clamped to 1..100.';
